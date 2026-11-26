// Manage workflow definition files requested by the Operations Portal.
package com.ganalimura.workflowservice.workflow;

import com.ganalimura.workflowservice.config.WorkflowProperties;
import org.springframework.stereotype.Service;
import org.yaml.snakeyaml.DumperOptions;
import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

@Service
public class WorkflowFileService {
    private final Path directory;
    private final Yaml yaml;

    public WorkflowFileService(WorkflowProperties properties) {
        directory = Paths.get(properties.getDirectory()).toAbsolutePath().normalize();
        DumperOptions options = new DumperOptions();
        options.setDefaultFlowStyle(DumperOptions.FlowStyle.BLOCK);
        options.setPrettyFlow(true);
        options.setIndent(2);
        yaml = new Yaml(options);
    }

    public Map<String, Object> save(Map<String, Object> document) throws IOException {
        validate(document);
        String id = (String) document.get("id");
        Files.createDirectories(directory);
        Path target = directory.resolve(id + ".yaml").normalize();
        if (!target.getParent().equals(directory)) throw new IllegalArgumentException("Invalid workflow id");

        Path temp = Files.createTempFile(directory, id, ".tmp");
        try {
            Files.writeString(temp, yaml.dump(document), StandardCharsets.UTF_8);
            try { Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (AtomicMoveNotSupportedException ex) {
                Files.move(temp, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } finally { Files.deleteIfExists(temp); }

        return Map.of("success", true, "id", id, "fileName", target.getFileName().toString(),
                "path", target.toString(), "message", "Workflow YAML saved");
    }

    public List<Map<String, String>> list() throws IOException {
        if (!Files.exists(directory)) return List.of();
        try (var files = Files.list(directory)) {
            return files.filter(Files::isRegularFile)
                .filter(p -> p.toString().endsWith(".yaml") || p.toString().endsWith(".yml"))
                .sorted()
                .map(p -> Map.of("fileName", p.getFileName().toString(), "path", p.toString()))
                .toList();
        }
    }

    public Map<String, Object> read(String id) throws IOException {
        Path path = safePath(id);
        if (!Files.exists(path)) throw new NoSuchFileException(path.toString());
        Object loaded = yaml.load(Files.readString(path, StandardCharsets.UTF_8));
        if (!(loaded instanceof Map<?, ?> map)) throw new IllegalArgumentException("YAML root must be an object");
        Map<String, Object> result = new LinkedHashMap<>();
        map.forEach((k, v) -> result.put(String.valueOf(k), v));
        validate(result);
        return result;
    }

    public Path safePath(String id) {
        if (id == null || !id.matches("[A-Za-z0-9][A-Za-z0-9_-]{0,79}")) {
            throw new IllegalArgumentException("Invalid workflow id");
        }
        Path path = directory.resolve(id + ".yaml").normalize();
        if (!path.getParent().equals(directory)) throw new IllegalArgumentException("Invalid workflow id");
        return path;
    }

    private void validate(Map<String, Object> doc) {
        for (String key : List.of("id", "type", "name", "steps")) {
            if (!doc.containsKey(key)) throw new IllegalArgumentException("Missing required workflow field: " + key);
        }
        String id = String.valueOf(doc.get("id"));
        if (!id.matches("[A-Za-z0-9][A-Za-z0-9_-]{0,79}")) throw new IllegalArgumentException("Invalid workflow id");
        if (!(doc.get("steps") instanceof List<?> steps) || steps.isEmpty())
            throw new IllegalArgumentException("steps must be a non-empty list");

        Set<String> ids = new HashSet<>();
        for (Object rawStep : steps) {
            if (!(rawStep instanceof Map<?, ?> step)) throw new IllegalArgumentException("Each step must be an object");
            String stepId = String.valueOf(step.get("id"));
            if (!stepId.matches("[A-Za-z0-9][A-Za-z0-9_-]{0,79}")) throw new IllegalArgumentException("Invalid step id: " + stepId);
            if (!ids.add(stepId)) throw new IllegalArgumentException("Duplicate step id: " + stepId);
            for (String key : List.of("apiname", "prompt")) {
                if (step.get(key) == null || String.valueOf(step.get(key)).isBlank())
                    throw new IllegalArgumentException("Step " + stepId + " requires " + key);
            }
        }
        Set<String> terminals = Set.of("end", "error", "finish", "stop", "c");
        for (Object rawStep : steps) {
            Map<?, ?> step = (Map<?, ?>) rawStep;
            for (String routeKey : List.of("onSuccess", "onError")) {
                Object routeObj = step.get(routeKey);
                if (routeObj instanceof Map<?, ?> route && route.get("gotoStep") != null) {
                    String target = String.valueOf(route.get("gotoStep"));
                    if (!ids.contains(target) && !terminals.contains(target.toLowerCase(Locale.ROOT)))
                        throw new IllegalArgumentException("Unknown " + routeKey + " target '" + target + "' in step " + step.get("id"));
                }
            }
        }
    }
}
