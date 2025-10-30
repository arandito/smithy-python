/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
package software.amazon.smithy.python.codegen.writer;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import software.amazon.smithy.codegen.core.CodegenException;
import software.amazon.smithy.utils.SmithyInternalApi;

/**
 * Converts CommonMark/HTML documentation to Google-style Markdown for Python docstrings.
 *
 * This converter uses the pandoc CLI tool to convert documentation from CommonMark/HTML
 * format to Markdown suitable for Python docstrings with Google-style formatting.
 *
 * Pandoc must be installed and available.
 */
@SmithyInternalApi
public final class MarkdownConverter {

    private static final int TIMEOUT_SECONDS = 10;

    // Private constructor to prevent instantiation
    private MarkdownConverter() {}

    /**
     * Converts HTML or CommonMark to Google-style Markdown using pandoc.
     *
     * @param input The input string (HTML or CommonMark)
     * @return Google-style Markdown formatted string
     */
    public static String convert(String input) {
        if (input == null || input.isEmpty()) {
            return "";
        }

        // TODO: Add support for commonmark -> html -> markdown for generic clients
        try {
            return convertWithPandoc(input);
        } catch (IOException | InterruptedException e) {
            throw new CodegenException("Failed to convert documentation using pandoc: " + e.getMessage(), e);
        }
    }

    /**
     * Calls pandoc CLI to convert documentation.
     *
     * @param input The input documentation string
     * @return Converted Markdown string
     * @throws IOException if process I/O fails
     * @throws InterruptedException if process is interrupted
     */
    private static String convertWithPandoc(String input)
            throws IOException, InterruptedException {
        ProcessBuilder processBuilder = new ProcessBuilder(
                "pandoc",
                "--from=html+raw_html",
                "--to=markdown",
                "--wrap=auto",
                "--columns=72");
        processBuilder.redirectErrorStream(true);

        Process process = processBuilder.start();

        // Write input to pandoc's stdin
        try (var outputStream = process.getOutputStream()) {
            outputStream.write(input.getBytes(StandardCharsets.UTF_8));
            outputStream.flush();
        }

        // Read output from pandoc's stdout
        StringBuilder output = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                output.append(line).append("\n");
            }
        }

        // Wait for process to complete
        boolean finished = process.waitFor(TIMEOUT_SECONDS, TimeUnit.SECONDS);
        if (!finished) {
            process.destroyForcibly();
            throw new CodegenException("Pandoc process timed out after " + TIMEOUT_SECONDS + " seconds");
        }

        int exitCode = process.exitValue();
        if (exitCode != 0) {
            throw new CodegenException(
                    "Pandoc failed with exit code " + exitCode + ": " + output.toString().trim());
        }

        String result = output.toString().trim();

        // Remove unnecessary backslash escapes that pandoc adds for markdown
        // These characters don't need escaping in Python docstrings
        result = result.replaceAll("\\\\([\\[\\]'{}()<>])", "$1");

        // Replace <note> and <important> tags with admonitions for mkdocstrings
        result = replaceAdmonitionTags(result, "note", "Note");
        result = replaceAdmonitionTags(result, "important", "Warning");

        // Escape Smithy format specifiers
        return result.replace("$", "$$");
    }

    /**
     * Replaces admonition tags (note, important) with Google-style format.
     *
     * @param text The text to process
     * @param tagName The tag name to replace (e.g., "note", "important")
     * @param label The label to use (e.g., "Note", "Warning")
     * @return Text with replaced admonitions
     */
    private static String replaceAdmonitionTags(String text, String tagName, String label) {
        // Match <tag>content</tag> across multiple lines
        Pattern pattern = Pattern.compile("<" + tagName + ">\\s*([\\s\\S]*?)\\s*</" + tagName + ">");
        Matcher matcher = pattern.matcher(text);
        StringBuffer result = new StringBuffer();

        while (matcher.find()) {
            // Extract the content between tags
            String content = matcher.group(1).trim();

            // Indent each line with 4 spaces
            String[] lines = content.split("\n");
            StringBuilder indented = new StringBuilder(label + ":\n");
            for (String line : lines) {
                indented.append("    ").append(line.trim()).append("\n");
            }

            matcher.appendReplacement(result, Matcher.quoteReplacement(indented.toString().trim()));
        }
        matcher.appendTail(result);

        return result.toString();
    }
}
