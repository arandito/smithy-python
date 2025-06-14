/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
package software.amazon.smithy.python.codegen;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import software.amazon.smithy.codegen.core.Symbol;
import software.amazon.smithy.model.knowledge.ServiceIndex;
import software.amazon.smithy.model.knowledge.TopDownIndex;
import software.amazon.smithy.model.shapes.OperationShape;
import software.amazon.smithy.model.shapes.ShapeId;
import software.amazon.smithy.model.traits.AuthTrait;
import software.amazon.smithy.python.codegen.integrations.AuthScheme;
import software.amazon.smithy.python.codegen.integrations.PythonIntegration;
import software.amazon.smithy.python.codegen.integrations.RuntimeClientPlugin;
import software.amazon.smithy.python.codegen.sections.GenerateHttpAuthSchemeResolverSection;
import software.amazon.smithy.python.codegen.writer.PythonWriter;
import software.amazon.smithy.utils.SmithyInternalApi;

/**
 * This class is responsible for generating the http auth scheme resolver and its configuration.
 */
@SmithyInternalApi
final class HttpAuthGenerator implements Runnable {

    private final PythonSettings settings;
    private final GenerationContext context;

    HttpAuthGenerator(GenerationContext context, PythonSettings settings) {
        this.settings = settings;
        this.context = context;
    }

    @Override
    public void run() {
        var supportedAuthSchemes = new HashMap<ShapeId, AuthScheme>();
        var service = context.settings().service(context.model());
        for (PythonIntegration integration : context.integrations()) {
            for (RuntimeClientPlugin plugin : integration.getClientPlugins(context)) {
                if (plugin.matchesService(context.model(), service)
                        && plugin.getAuthScheme().isPresent()
                        && plugin.getAuthScheme().get().getApplicationProtocol().isHttpProtocol()) {
                    var scheme = plugin.getAuthScheme().get();
                    supportedAuthSchemes.put(scheme.getAuthTrait(), scheme);
                }
            }
        }

        var resolver = CodegenUtils.getHttpAuthSchemeResolverSymbol(settings);
        context.writerDelegator().useFileWriter(resolver.getDefinitionFile(), resolver.getNamespace(), writer -> {
            generateAuthSchemeResolver(writer, resolver, supportedAuthSchemes);
        });
    }

    private void generateAuthSchemeResolver(
            PythonWriter writer,
            Symbol resolverSymbol,
            Map<ShapeId, AuthScheme> supportedAuthSchemes
    ) {
        var resolvedAuthSchemes = ServiceIndex.of(context.model())
                .getEffectiveAuthSchemes(settings.service())
                .keySet()
                .stream()
                .filter(supportedAuthSchemes::containsKey)
                .map(supportedAuthSchemes::get)
                .toList();

        writer.pushState(new GenerateHttpAuthSchemeResolverSection(resolvedAuthSchemes));
        writer.addDependency(SmithyPythonDependency.SMITHY_CORE);
        writer.addDependency(SmithyPythonDependency.SMITHY_HTTP);
        writer.addImport("smithy_core.interfaces.auth", "AuthOption", "AuthOptionProtocol");
        writer.addImport("smithy_core.auth", "AuthParams");
        writer.addStdlibImport("typing", "Any");
        writer.write("""
                class $1L:
                    def resolve_auth_scheme(self, auth_parameters: AuthParams[Any, Any]) -> list[AuthOptionProtocol]:
                        auth_options: list[AuthOptionProtocol] = []

                        ${2C|}
                        ${3C|}

                """,
                resolverSymbol.getName(),
                writer.consumer(w -> writeOperationAuthOptions(w, supportedAuthSchemes)),
                writer.consumer(w -> writeAuthOptions(w, resolvedAuthSchemes)));
        writer.popState();
    }

    private void writeOperationAuthOptions(PythonWriter writer, Map<ShapeId, AuthScheme> supportedAuthSchemes) {
        var operations = TopDownIndex.of(context.model()).getContainedOperations(settings.service());
        var serviceIndex = ServiceIndex.of(context.model());
        for (OperationShape operation : operations) {
            if (!operation.hasTrait(AuthTrait.class)) {
                continue;
            }

            var operationAuthSchemes = serviceIndex
                    .getEffectiveAuthSchemes(settings.service(), operation)
                    .keySet()
                    .stream()
                    .filter(supportedAuthSchemes::containsKey)
                    .map(supportedAuthSchemes::get)
                    .toList();

            writer.write("""
                    if auth_parameters.operation == $S:
                        ${C|}

                    """, operation.getId().getName(), writer.consumer(w -> writeAuthOptions(w, operationAuthSchemes)));
        }
    }

    private void writeAuthOptions(PythonWriter writer, List<AuthScheme> authSchemes) {
        var authOptionInitializers = authSchemes.stream()
                .map(scheme -> scheme.getAuthOptionGenerator(context))
                .toList();
        writer.pushState();
        writer.putContext("authOptionInitializers", authOptionInitializers);
        writer.write("""
                ${#authOptionInitializers}
                if (option := ${value:T}(auth_parameters)) is not None:
                    auth_options.append(option)

                ${/authOptionInitializers}
                return auth_options
                """);
        writer.popState();
    }
}
