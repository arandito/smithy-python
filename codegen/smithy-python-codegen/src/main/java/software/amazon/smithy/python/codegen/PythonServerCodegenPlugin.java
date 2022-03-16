/*
 * Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License").
 * You may not use this file except in compliance with the License.
 * A copy of the License is located at
 *
 *   http://aws.amazon.com/apache2.0
 *
 * or in the "license" file accompanying this file. This file is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
 * express or implied. See the License for the specific language governing
 * permissions and limitations under the License.
 */

package software.amazon.smithy.python.codegen;

import static software.amazon.smithy.python.codegen.PythonSettings.ArtifactType;

import software.amazon.smithy.build.PluginContext;
import software.amazon.smithy.build.SmithyBuildPlugin;
import software.amazon.smithy.utils.SmithyInternalApi;

/**
 * Plugin to trigger Python SSDK code generation.
 */
@SmithyInternalApi
public final class PythonServerCodegenPlugin implements SmithyBuildPlugin {
    @Override
    public String getName() {
        return "python-ssdk-codegen";
    }

    @Override
    public void execute(PluginContext context) {
        new CodegenVisitor(context, ArtifactType.SSDK).execute();
    }
}
