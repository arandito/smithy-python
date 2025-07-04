/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
package software.amazon.smithy.python.codegen;

import static java.lang.String.format;

import java.util.Locale;
import java.util.logging.Logger;
import software.amazon.smithy.codegen.core.ReservedWordSymbolProvider;
import software.amazon.smithy.codegen.core.ReservedWordsBuilder;
import software.amazon.smithy.codegen.core.Symbol;
import software.amazon.smithy.codegen.core.SymbolProvider;
import software.amazon.smithy.codegen.core.SymbolReference;
import software.amazon.smithy.model.Model;
import software.amazon.smithy.model.loader.Prelude;
import software.amazon.smithy.model.shapes.BigDecimalShape;
import software.amazon.smithy.model.shapes.BigIntegerShape;
import software.amazon.smithy.model.shapes.BlobShape;
import software.amazon.smithy.model.shapes.BooleanShape;
import software.amazon.smithy.model.shapes.ByteShape;
import software.amazon.smithy.model.shapes.DocumentShape;
import software.amazon.smithy.model.shapes.DoubleShape;
import software.amazon.smithy.model.shapes.EnumShape;
import software.amazon.smithy.model.shapes.FloatShape;
import software.amazon.smithy.model.shapes.IntEnumShape;
import software.amazon.smithy.model.shapes.IntegerShape;
import software.amazon.smithy.model.shapes.ListShape;
import software.amazon.smithy.model.shapes.LongShape;
import software.amazon.smithy.model.shapes.MapShape;
import software.amazon.smithy.model.shapes.MemberShape;
import software.amazon.smithy.model.shapes.OperationShape;
import software.amazon.smithy.model.shapes.ResourceShape;
import software.amazon.smithy.model.shapes.ServiceShape;
import software.amazon.smithy.model.shapes.Shape;
import software.amazon.smithy.model.shapes.ShapeVisitor;
import software.amazon.smithy.model.shapes.ShortShape;
import software.amazon.smithy.model.shapes.StringShape;
import software.amazon.smithy.model.shapes.StructureShape;
import software.amazon.smithy.model.shapes.TimestampShape;
import software.amazon.smithy.model.shapes.UnionShape;
import software.amazon.smithy.model.traits.ErrorTrait;
import software.amazon.smithy.model.traits.MediaTypeTrait;
import software.amazon.smithy.model.traits.SparseTrait;
import software.amazon.smithy.model.traits.StreamingTrait;
import software.amazon.smithy.utils.CaseUtils;
import software.amazon.smithy.utils.MediaType;
import software.amazon.smithy.utils.SmithyInternalApi;
import software.amazon.smithy.utils.StringUtils;

/**
 * Responsible for type mapping and file/identifier formatting.
 *
 * <p>Reserved words for Python are automatically escaped so that they are
 * suffixed with "_". See "reserved-words.txt" for the list of words.
 *
 * <p>{@see {@link SymbolProperties}} for various additional properties that
 * may be attached to symbols.
 */
@SmithyInternalApi
public final class PythonSymbolProvider implements SymbolProvider, ShapeVisitor<Symbol> {

    private static final Logger LOGGER = Logger.getLogger(PythonSymbolProvider.class.getName());
    private static final String SHAPES_FILE = "models";
    private static final String SCHEMAS_FILE = "_private/schemas";

    private final Model model;
    private final ReservedWordSymbolProvider.Escaper escaper;
    private final ReservedWordSymbolProvider.Escaper errorMemberEscaper;
    private final PythonSettings settings;
    private final ServiceShape service;

    public PythonSymbolProvider(Model model, PythonSettings settings) {
        this.model = model;
        this.settings = settings;
        this.service = model.expectShape(settings.service(), ServiceShape.class);

        // Load reserved words from new-line delimited files.
        var reservedClassNames = new ReservedWordsBuilder()
                .loadWords(PythonSymbolProvider.class.getResource("reserved-class-names.txt"), this::escapeWord)
                .build();
        var reservedMemberNamesBuilder = new ReservedWordsBuilder()
                .loadWords(PythonSymbolProvider.class.getResource("reserved-member-names.txt"), this::escapeWord);

        // Reserved words that only apply to error members.
        var reservedErrorMembers = new ReservedWordsBuilder()
                .loadWords(PythonSymbolProvider.class.getResource("reserved-error-member-names.txt"), this::escapeWord);

        escaper = ReservedWordSymbolProvider.builder()
                .nameReservedWords(reservedClassNames)
                .memberReservedWords(reservedMemberNamesBuilder.build())
                // Only escape words when the symbol has a definition file to
                // prevent escaping intentional references to built-in types.
                .escapePredicate((shape, symbol) -> !StringUtils.isEmpty(symbol.getDefinitionFile()))
                .buildEscaper();

        errorMemberEscaper = ReservedWordSymbolProvider.builder()
                .memberReservedWords(reservedErrorMembers.build())
                .escapePredicate((shape, symbol) -> !StringUtils.isEmpty(symbol.getDefinitionFile()))
                .buildEscaper();
    }

    private String escapeWord(String word) {
        return word + "_";
    }

    @Override
    public Symbol toSymbol(Shape shape) {
        Symbol symbol = shape.accept(this);
        LOGGER.fine(() -> format("Creating symbol from %s: %s", shape, symbol));
        return escaper.escapeSymbol(shape, symbol);
    }

    @Override
    public String toMemberName(MemberShape shape) {
        if (CodegenUtils.isErrorMessage(model, shape)) {
            return "message";
        }

        var memberName = escaper.escapeMemberName(CaseUtils.toSnakeCase(shape.getMemberName()));

        // Escape words that are only reserved for error members.
        if (shape.hasTrait(ErrorTrait.class)) {
            memberName = errorMemberEscaper.escapeMemberName(memberName);
        }

        var container = model.expectShape(shape.getContainer());
        if (container.isEnumShape() || container.isIntEnumShape()) {
            memberName = memberName.toUpperCase(Locale.ENGLISH);
        }
        return memberName;
    }

    private String getDefaultShapeName(Shape shape) {
        // Use the service-aliased name
        return StringUtils.capitalize(shape.getId().getName(service));
    }

    @Override
    public Symbol blobShape(BlobShape shape) {
        // see: https://smithy.io/2.0/spec/streaming.html#smithy-api-streaming-trait
        if (shape.hasTrait(StreamingTrait.class)) {
            return createSymbolBuilder(shape, "StreamingBlob")
                    .namespace("smithy_core.aio.interfaces", ".")
                    .addDependency(SmithyPythonDependency.SMITHY_CORE)
                    .build();
        }

        // see: https://smithy.io/2.0/spec/protocol-traits.html#smithy-api-mediatype-trait
        if (shape.hasTrait(MediaTypeTrait.class)) {
            var mediaType = shape.expectTrait(MediaTypeTrait.class).getValue();
            if (MediaType.isJson(mediaType)) {
                return createSymbolBuilder(shape, "bytes | JsonBlob")
                        .addReference(Symbol.builder()
                                .name("JsonBlob")
                                .namespace("smithy_core.types", ".")
                                .addDependency(SmithyPythonDependency.SMITHY_CORE)
                                .build())
                        .build();
            }
        }
        return createSymbolBuilder(shape, "bytes").build();
    }

    @Override
    public Symbol booleanShape(BooleanShape shape) {
        return createSymbolBuilder(shape, "bool").build();
    }

    @Override
    public Symbol listShape(ListShape shape) {
        Symbol reference = toSymbol(shape.getMember());
        // see: https://smithy.io/2.0/spec/type-refinement-traits.html#smithy-api-sparse-trait
        String type = String.format(shape.hasTrait(SparseTrait.class) ? "%s | None" : "%s", reference.getName());
        var builder = createSymbolBuilder(shape, "list[" + type + "]")
                .addReference(reference);

        builder.putProperty(SymbolProperties.SERIALIZER,
                createGeneratedSymbolBuilder(
                        shape,
                        "_serialize_" + CaseUtils.toSnakeCase(shape.getId().getName()),
                        SHAPES_FILE,
                        false)
                        .build());

        builder.putProperty(SymbolProperties.DESERIALIZER,
                createGeneratedSymbolBuilder(
                        shape,
                        "_deserialize_" + CaseUtils.toSnakeCase(shape.getId().getName()),
                        SHAPES_FILE,
                        false)
                        .build());

        return builder.build();
    }

    @Override
    public Symbol mapShape(MapShape shape) {
        Symbol reference = toSymbol(shape.getValue());
        // see: https://smithy.io/2.0/spec/type-refinement-traits.html#smithy-api-sparse-trait
        String type = String.format(shape.hasTrait(SparseTrait.class) ? "%s | None" : "%s", reference.getName());
        var builder = createSymbolBuilder(shape, "dict[str, " + type + "]")
                .addReference(reference);

        builder.putProperty(SymbolProperties.SERIALIZER,
                createGeneratedSymbolBuilder(
                        shape,
                        "_serialize_" + CaseUtils.toSnakeCase(shape.getId().getName()),
                        SHAPES_FILE,
                        false)
                        .build());

        builder.putProperty(SymbolProperties.DESERIALIZER,
                createGeneratedSymbolBuilder(
                        shape,
                        "_deserialize_" + CaseUtils.toSnakeCase(shape.getId().getName()),
                        SHAPES_FILE,
                        false)
                        .build());

        return builder.build();
    }

    @Override
    public Symbol byteShape(ByteShape shape) {
        return createSymbolBuilder(shape, "int").build();
    }

    @Override
    public Symbol shortShape(ShortShape shape) {
        return createSymbolBuilder(shape, "int").build();
    }

    @Override
    public Symbol integerShape(IntegerShape shape) {
        return createSymbolBuilder(shape, "int").build();
    }

    @Override
    public Symbol longShape(LongShape shape) {
        return createSymbolBuilder(shape, "int").build();
    }

    @Override
    public Symbol floatShape(FloatShape shape) {
        return createSymbolBuilder(shape, "float").build();
    }

    @Override
    public Symbol documentShape(DocumentShape shape) {
        return createSymbolBuilder(shape, "Document")
                .namespace("smithy_core.documents", ".")
                .addDependency(SmithyPythonDependency.SMITHY_CORE)
                .build();
    }

    @Override
    public Symbol doubleShape(DoubleShape shape) {
        return createSymbolBuilder(shape, "float").build();
    }

    @Override
    public Symbol bigIntegerShape(BigIntegerShape shape) {
        return createSymbolBuilder(shape, "int").build();
    }

    @Override
    public Symbol bigDecimalShape(BigDecimalShape shape) {
        return createStdlibSymbol(shape, "Decimal", "decimal");
    }

    @Override
    public Symbol operationShape(OperationShape shape) {
        // Operation names are escaped like members because ultimately they're
        // properties on an object too.
        var methodName = escaper.escapeMemberName(CaseUtils.toSnakeCase(shape.getId().getName(service)));
        var methodSymbol = createGeneratedSymbolBuilder(shape, methodName, "client", false)
                .putProperty(SymbolProperties.IMPORTABLE, false)
                .build();

        // We add a symbol for the method in the client as a property, whereas the actual
        // operation symbol points to the generated type for it
        var name = CaseUtils.toSnakeCase(getDefaultShapeName(shape)).toUpperCase(Locale.ENGLISH);
        return createGeneratedSymbolBuilder(shape, name, SHAPES_FILE)
                .putProperty(SymbolProperties.OPERATION_METHOD, methodSymbol)
                .build();
    }

    @Override
    public Symbol resourceShape(ResourceShape shape) {
        // TODO: implement resources
        return createStdlibSymbol(shape, "Any", "typing");
    }

    @Override
    public Symbol serviceShape(ServiceShape shape) {
        var name = getDefaultShapeName(shape);
        return createGeneratedSymbolBuilder(shape, name, "client").build();
    }

    @Override
    public Symbol stringShape(StringShape shape) {
        var builder = createSymbolBuilder(shape, "str");
        // see: https://smithy.io/2.0/spec/protocol-traits.html#smithy-api-mediatype-trait
        if (shape.hasTrait(MediaTypeTrait.class)) {
            var mediaType = shape.expectTrait(MediaTypeTrait.class).getValue();
            if (MediaType.isJson(mediaType)) {
                return createSymbolBuilder(shape, "str | JsonString")
                        .addReference(Symbol.builder()
                                .name("JsonString")
                                .namespace("smithy_core.types", ".")
                                .addDependency(SmithyPythonDependency.SMITHY_CORE)
                                .build())
                        .build();
            }
        }
        return builder.build();
    }

    @Override
    public Symbol enumShape(EnumShape shape) {
        return genericEnum(shape);
    }

    @Override
    public Symbol intEnumShape(IntEnumShape shape) {
        return genericEnum(shape);
    }

    private Symbol genericEnum(Shape shape) {
        var enumSymbol = createGeneratedSymbolBuilder(shape, getDefaultShapeName(shape), SHAPES_FILE).build();

        // We add this enum symbol as a property on a generic string/int symbol
        // rather than returning the enum symbol directly because we only
        // generate the enum constants for convenience. We actually want
        // to pass around plain types rather than what is effectively
        // a namespace class.
        return createSymbolBuilder(shape, shape.isEnumShape() ? "str" : "int")
                .putProperty(SymbolProperties.ENUM_SYMBOL, escaper.escapeSymbol(shape, enumSymbol))
                .build();
    }

    @Override
    public Symbol structureShape(StructureShape shape) {
        String name = getDefaultShapeName(shape);
        return createGeneratedSymbolBuilder(shape, name, SHAPES_FILE).build();
    }

    @Override
    public Symbol unionShape(UnionShape shape) {
        String name = getDefaultShapeName(shape);

        var unknownName = name + "Unknown";
        var unknownSymbol = createGeneratedSymbolBuilder(shape, unknownName, SHAPES_FILE).build();
        var builder = createGeneratedSymbolBuilder(shape, name, SHAPES_FILE)
                .putProperty(SymbolProperties.UNION_UNKNOWN, unknownSymbol);

        builder.putProperty(SymbolProperties.DESERIALIZER,
                createGeneratedSymbolBuilder(
                        shape,
                        "_" + name + "Deserializer",
                        SHAPES_FILE,
                        false)
                        .build());

        return builder.build();
    }

    @Override
    public Symbol memberShape(MemberShape shape) {
        var container = model.expectShape(shape.getContainer());
        if (container.isUnionShape()) {
            // Union members, unlike other shape members, have types generated for them.
            var containerSymbol = container.accept(this);
            var name = containerSymbol.getName() + StringUtils.capitalize(shape.getMemberName());
            return createGeneratedSymbolBuilder(shape, name, SHAPES_FILE, false)
                    .putProperty(SymbolProperties.SCHEMA, containerSymbol.expectProperty(SymbolProperties.SCHEMA))
                    .build();
        }
        return toSymbol(model.expectShape(shape.getTarget()));
    }

    @Override
    public Symbol timestampShape(TimestampShape shape) {
        return createStdlibSymbol(shape, "datetime", "datetime");
    }

    private Symbol.Builder createSymbolBuilder(Shape shape, String typeName, boolean includeSchema) {
        var builder = Symbol.builder()
                .putProperty(SymbolProperties.SHAPE, shape)
                .name(typeName);
        if (includeSchema) {
            builder.putProperty(SymbolProperties.SCHEMA, createSchemaSymbol(shape));
        }
        return builder;
    }

    private SymbolReference createSchemaSymbol(Shape shape) {
        var schemaSymbolBuilder = Symbol.builder()
                .name(CaseUtils.toSnakeCase(shape.getId().getName(service)).toUpperCase(Locale.ENGLISH));
        if (Prelude.isPreludeShape(shape)) {
            schemaSymbolBuilder
                    .namespace("smithy_core.prelude", ".")
                    .addDependency(SmithyPythonDependency.SMITHY_CORE);
        } else {
            schemaSymbolBuilder
                    .namespace(String.format("%s.%s", settings.moduleName(), SCHEMAS_FILE.replace('/', '.')), ".")
                    .definitionFile(String.format("./src/%s/%s.py", settings.moduleName(), SCHEMAS_FILE));
        }
        var schemaSymbol = schemaSymbolBuilder.build();
        return SymbolReference.builder()
                .alias("_SCHEMA_" + schemaSymbol.getName())
                .symbol(schemaSymbol)
                .build();
    }

    private Symbol.Builder createSymbolBuilder(Shape shape, String typeName) {
        return createSymbolBuilder(shape, typeName, true);
    }

    private Symbol.Builder createGeneratedSymbolBuilder(
            Shape shape,
            String typeName,
            String file,
            boolean includeSchema
    ) {
        var namespace = String.format("%s.%s", settings.moduleName(), file.replace('/', '.'));
        var filename = String.format("./src/%s/%s.py", settings.moduleName(), file);
        return createSymbolBuilder(shape, typeName, includeSchema)
                .namespace(namespace, ".")
                .definitionFile(filename);
    }

    private Symbol.Builder createGeneratedSymbolBuilder(Shape shape, String typeName, String file) {
        return createGeneratedSymbolBuilder(shape, typeName, file, true);
    }

    private Symbol createStdlibSymbol(Shape shape, String typeName, String namespace) {
        return createSymbolBuilder(shape, typeName)
                .putProperty(SymbolProperties.STDLIB, true)
                .namespace(namespace, ".")
                .build();
    }
}
