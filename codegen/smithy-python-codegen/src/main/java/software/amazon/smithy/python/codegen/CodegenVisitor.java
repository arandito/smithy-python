/*
 * Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License").
 * You may not use this file except in compliance with the License.
 * A copy of the License is located at
 *
 *  http://aws.amazon.com/apache2.0
 *
 * or in the "license" file accompanying this file. This file is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
 * express or implied. See the License for the specific language governing
 * permissions and limitations under the License.
 */

package software.amazon.smithy.python.codegen;

import static java.lang.String.format;
import static software.amazon.smithy.python.codegen.PythonSettings.ArtifactType;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.ServiceLoader;
import java.util.Set;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import software.amazon.smithy.build.FileManifest;
import software.amazon.smithy.build.PluginContext;
import software.amazon.smithy.codegen.core.CodegenException;
import software.amazon.smithy.codegen.core.SmithyIntegration;
import software.amazon.smithy.codegen.core.Symbol;
import software.amazon.smithy.codegen.core.SymbolProvider;
import software.amazon.smithy.codegen.core.TopologicalIndex;
import software.amazon.smithy.model.Model;
import software.amazon.smithy.model.neighbor.Walker;
import software.amazon.smithy.model.shapes.CollectionShape;
import software.amazon.smithy.model.shapes.ListShape;
import software.amazon.smithy.model.shapes.MapShape;
import software.amazon.smithy.model.shapes.ServiceShape;
import software.amazon.smithy.model.shapes.SetShape;
import software.amazon.smithy.model.shapes.Shape;
import software.amazon.smithy.model.shapes.ShapeId;
import software.amazon.smithy.model.shapes.ShapeVisitor;
import software.amazon.smithy.model.shapes.StringShape;
import software.amazon.smithy.model.shapes.StructureShape;
import software.amazon.smithy.model.shapes.UnionShape;
import software.amazon.smithy.model.traits.EnumTrait;
import software.amazon.smithy.model.transform.ModelTransformer;
import software.amazon.smithy.python.codegen.integration.GenerationContext;
import software.amazon.smithy.python.codegen.integration.ProtocolGenerator;
import software.amazon.smithy.python.codegen.integration.PythonIntegration;
import software.amazon.smithy.utils.CodeInterceptor;
import software.amazon.smithy.utils.CodeSection;
import software.amazon.smithy.utils.SmithyInternalApi;

/**
 * Orchestrates Python client generation.
 */
@SmithyInternalApi
final class CodegenVisitor extends ShapeVisitor.Default<Void> {

    private static final Logger LOGGER = Logger.getLogger(CodegenVisitor.class.getName());

    private final PythonSettings settings;
    private final Model model;
    private final Model modelWithoutTraitShapes;
    private final ServiceShape service;
    private final FileManifest fileManifest;
    private final SymbolProvider symbolProvider;
    private final PythonDelegator writers;
    private Set<Shape> recursiveShapes;
    private final List<PythonIntegration> integrations;
    private final GenerationContext generationContext;
    private final ProtocolGenerator protocolGenerator;
    private final ApplicationProtocol applicationProtocol;

    CodegenVisitor(PluginContext context, ArtifactType artifactType) {
        // Load all integrations.
        ClassLoader loader = context.getPluginClassLoader().orElse(getClass().getClassLoader());
        LOGGER.info("Attempting to discover PythonIntegrations from the classpath...");
        List<PythonIntegration> loadedIntegrations = new ArrayList<>();
        ServiceLoader.load(PythonIntegration.class, loader)
                .forEach(integration -> {
                    LOGGER.info(() -> "Adding PythonIntegration: " + integration.getClass().getName());
                    loadedIntegrations.add(integration);
                });
        integrations = Collections.unmodifiableList(SmithyIntegration.sort(loadedIntegrations));

        // Allow integrations to modify the model before generation
        PythonSettings pythonSettings = PythonSettings.from(context.getSettings(), artifactType);
        ModelTransformer transformer = ModelTransformer.create();
        Model modifiedModel = transformer.createDedicatedInputAndOutput(context.getModel(), "Input", "Output");
        for (PythonIntegration integration : integrations) {
            modifiedModel = integration.preprocessModel(modifiedModel, pythonSettings);
        }

        settings = pythonSettings;
        model = modifiedModel;
        modelWithoutTraitShapes = transformer.getModelWithoutTraitShapes(model);
        service = settings.getService(model);
        fileManifest = context.getFileManifest();
        LOGGER.info(() -> "Generating Python client for service " + service.getId());

        // Decorate the symbol provider using integrations.
        SymbolProvider resolvedProvider = artifactType.createSymbolProvider(model, settings);
        for (PythonIntegration integration : integrations) {
            resolvedProvider = integration.decorateSymbolProvider(model, settings, resolvedProvider);
        }
        symbolProvider = SymbolProvider.cache(resolvedProvider);

        // Resolve the nullable protocol generator and application protocol.
        protocolGenerator = resolveProtocolGenerator(integrations, service, settings);
        applicationProtocol = protocolGenerator == null
                ? ApplicationProtocol.createDefaultHttpApplicationProtocol()
                : protocolGenerator.getApplicationProtocol();

        // Finalize the generation context
        generationContext = GenerationContext.builder()
                .model(model)
                .settings(settings)
                .symbolProvider(symbolProvider)
                .fileManifest(fileManifest)
                .build();

        // Gather all registered interceptors from integrations
        List<CodeInterceptor<? extends CodeSection, PythonWriter>> interceptors = new ArrayList<>();
        for (PythonIntegration integration : integrations) {
            interceptors.addAll(integration.interceptors(generationContext));
        }

        writers = new PythonDelegator(settings, model, fileManifest, symbolProvider, interceptors);
    }

    private ProtocolGenerator resolveProtocolGenerator(
            List<PythonIntegration> integrations,
            ServiceShape service,
            PythonSettings settings
    ) {
        // Collect all the supported protocol generators.
        Map<ShapeId, ProtocolGenerator> generators = new HashMap<>();
        for (PythonIntegration integration : integrations) {
            for (ProtocolGenerator generator : integration.getProtocolGenerators()) {
                generators.put(generator.getProtocol(), generator);
            }
        }

        ShapeId protocolName;
        try {
            protocolName = settings.resolveServiceProtocol(model, service, generators.keySet());
        } catch (CodegenException e) {
            LOGGER.warning("Unable to find a protocol generator for " + service.getId() + ": " + e.getMessage());
            protocolName = null;
        }

        return protocolName != null ? generators.get(protocolName) : null;
    }

    void execute() {
        // Generate models that are connected to the service being generated.
        LOGGER.fine("Walking shapes from " + service.getId() + " to find shapes to generate");
        Collection<Shape> shapeSet = new Walker(modelWithoutTraitShapes).walkShapes(service);
        Model prunedModel = Model.builder().addShapes(shapeSet).build();

        generateDefaultTimestamp(prunedModel);
        generateServiceErrors();

        // Sort shapes in a reverse topological order so that we can reduce the
        // number of necessary forward references.
        var topologicalIndex = TopologicalIndex.of(prunedModel);
        recursiveShapes = topologicalIndex.getRecursiveShapes();
        for (Shape shape : topologicalIndex.getOrderedShapes()) {
            shape.accept(this);
        }
        for (Shape shape : topologicalIndex.getRecursiveShapes()) {
            shape.accept(this);
        }

        SetupGenerator.generateSetup(settings, writers);

        LOGGER.fine("Flushing python writers");
        writers.flushWriters();
        generateInits();

        // Allows integrations to interact with the generated output files
        // in the file manifest.
        for (PythonIntegration integration : integrations) {
            integration.customize(generationContext);
        }

        postProcess();
    }

    private void generateServiceErrors() {
        var serviceError = CodegenUtils.getServiceError(settings);
        writers.useFileWriter(serviceError.getDefinitionFile(), serviceError.getNamespace(), writer -> {
            // TODO: subclass a shared error
            writer.openBlock("class $L(Exception):", "", serviceError.getName(), () -> {
                writer.writeDocs("Base error for all errors in the service.");
                writer.write("pass");
            });
        });

        var apiError = CodegenUtils.getApiError(settings);
        writers.useFileWriter(apiError.getDefinitionFile(), apiError.getNamespace(), writer -> {
            writer.addStdlibImport("typing", "Generic");
            writer.addStdlibImport("typing", "TypeVar");
            writer.write("T = TypeVar('T')");
            writer.openBlock("class $L($T, Generic[T]):", "", apiError.getName(), serviceError, () -> {
                writer.writeDocs("Base error for all api errors in the service.");
                writer.write("code: T");
                writer.openBlock("def __init__(self, message: str):", "", () -> {
                    writer.write("super().__init__(message)");
                    writer.write("self.message = message");
                });
            });

            var unknownApiError = CodegenUtils.getUnknownApiError(settings);
            writer.addStdlibImport("typing", "Literal");
            writer.openBlock("class $L($T[Literal['Unknown']]):", "", unknownApiError.getName(), apiError, () -> {
                writer.writeDocs("Error representing any unknown api errors");
                writer.write("code: Literal['Unknown'] = 'Unknown'");
            });
        });


    }

    /**
     * Creates __init__.py files where not already present.
     */
    private void generateInits() {
        var directories = fileManifest.getFiles().stream()
                .filter(path -> !path.getParent().equals(fileManifest.getBaseDir()))
                .collect(Collectors.groupingBy(Path::getParent, Collectors.toSet()));
        for (var entry : directories.entrySet()) {
            var initPath = entry.getKey().resolve("__init__.py");
            if (!entry.getValue().contains(initPath)) {
                fileManifest.writeFile(initPath, "# Code generated by smithy-python-codegen DO NOT EDIT.\n");
            }
        }
    }

    private void postProcess() {
        Pattern versionPattern = Pattern.compile("Python \\d\\.(?<minor>\\d+)\\.(?<patch>\\d+)");

        String output;
        try {
            LOGGER.info("Attempting to discover python version");
            output = CodegenUtils.runCommand("python3 --version", fileManifest.getBaseDir()).strip();
        } catch (CodegenException e) {
            LOGGER.warning("Unable to find python on the path. Skipping formatting and type checking.");
            return;
        }
        var matcher = versionPattern.matcher(output);
        if (!matcher.find()) {
            LOGGER.warning("Unable to parse python version string. Skipping formatting and type checking.");
        }
        int minorVersion = Integer.parseInt(matcher.group("minor"));
        if (minorVersion < 9) {
            LOGGER.warning(format("""
                    Found incompatible python version 3.%s.%s, expected 3.9.0 or greater. \
                    Skipping formatting and type checking.""",
                    matcher.group("minor"), matcher.group("patch")));
            return;
        }
        LOGGER.info("Verifying python files");
        for (var file : fileManifest.getFiles()) {
            var fileName = file.getFileName();
            if (fileName == null || !fileName.endsWith(".py")) {
                continue;
            }
            CodegenUtils.runCommand("python3 " + file, fileManifest.getBaseDir());
        }
        formatCode();
        runMypy();
    }

    private void formatCode() {
        try {
            CodegenUtils.runCommand("python3 -m black -h", fileManifest.getBaseDir());
        } catch (CodegenException e) {
            LOGGER.warning("Unable to find the python package black. Skipping formatting.");
            return;
        }
        LOGGER.info("Running code formatter on generated code");
        CodegenUtils.runCommand("python3 -m black . --exclude \"\"", fileManifest.getBaseDir());
    }

    private void runMypy() {
        try {
            CodegenUtils.runCommand("python3 -m mypy -h", fileManifest.getBaseDir());
        } catch (CodegenException e) {
            LOGGER.warning("Unable to find the python package mypy. Skipping type checking.");
            return;
        }
        LOGGER.info("Running mypy on generated code");
        CodegenUtils.runCommand("python3 -m mypy .", fileManifest.getBaseDir());
    }

    private void generateDefaultTimestamp(Model model) {
        var timestamp = CodegenUtils.getDefaultTimestamp(settings);
        if (!model.getTimestampShapes().isEmpty()) {
            writers.useFileWriter(timestamp.getDefinitionFile(), timestamp.getNamespace(), writer -> {
                writer.addStdlibImport("datetime", "datetime");
                writer.write("$L = datetime(1970, 1, 1)", timestamp.getName());
            });
        }
    }

    @Override
    protected Void getDefault(Shape shape) {
        return null;
    }

    @Override
    public Void stringShape(StringShape shape) {
        if (shape.hasTrait(EnumTrait.class)) {
            writers.useShapeWriter(shape, writer -> new EnumGenerator(model, symbolProvider, writer, shape).run());
        }
        return null;
    }

    @Override
    public Void structureShape(StructureShape shape) {
        writers.useShapeWriter(shape, writer -> new StructureGenerator(
                model, settings, symbolProvider, writer, shape, recursiveShapes).run());
        return null;
    }

    @Override
    public Void unionShape(UnionShape shape) {
        writers.useShapeWriter(shape, writer -> new UnionGenerator(
                model, symbolProvider, writer, shape, recursiveShapes).run());
        return null;
    }

    @Override
    public Void listShape(ListShape shape) {
        return collectionShape(shape);
    }

    @Override
    public Void setShape(SetShape shape) {
        return collectionShape(shape);
    }

    private Void collectionShape(CollectionShape shape) {
        var optionalAsDictSymbol = symbolProvider.toSymbol(shape).getProperty("asDict", Symbol.class);
        optionalAsDictSymbol.ifPresent(asDictSymbol -> {
            writers.useFileWriter(asDictSymbol.getDefinitionFile(), asDictSymbol.getNamespace(), writer -> {
                new CollectionGenerator(model, symbolProvider, writer, shape).run();
            });
        });
        return null;
    }

    @Override
    public Void mapShape(MapShape shape) {
        var optionalAsDictSymbol = symbolProvider.toSymbol(shape).getProperty("asDict", Symbol.class);
        optionalAsDictSymbol.ifPresent(asDictSymbol -> {
            writers.useFileWriter(asDictSymbol.getDefinitionFile(), asDictSymbol.getNamespace(), writer -> {
                new MapGenerator(model, symbolProvider, writer, shape).run();
            });
        });
        return null;
    }
}
