// Coordinate workflow execution requests from the Operations Portal.
package com.ganalimura.workflowservice.workflow;

import com.ganalimura.workflowservice.service.AiClientService;
import com.ganalimura.workflowservice.service.SterlingInteropService;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.util.*;

@Service
public class WorkflowExecutionService {
    private final WorkflowFileService workflowFiles;
    private final AiClientService aiClient;
    private final SterlingInteropService omsInterop;

    public WorkflowExecutionService(WorkflowFileService workflowFiles, AiClientService aiClient,
                                    SterlingInteropService omsInterop) {
        this.workflowFiles = workflowFiles;
        this.aiClient = aiClient;
        this.omsInterop = omsInterop;
    }

    /**
     * Executes steps by ID. processStructuredRequest calls the user's Python AI endpoint.
     * Other apiname values are treated as OMS API names and send the XML extracted from prompt to OMS.
     */
    public Map<String, Object> run(String workflowId) throws IOException {
        Map<String, Object> workflow = workflowFiles.read(workflowId);
        List<?> steps = (List<?>) workflow.get("steps");
        Map<String, Map<?, ?>> byId = new LinkedHashMap<>();
        for (Object o : steps) {
            Map<?, ?> step = (Map<?, ?>) o;
            byId.put(String.valueOf(step.get("id")), step);
        }

        String currentId = String.valueOf(((Map<?, ?>) steps.get(0)).get("id"));
        List<Map<String, Object>> history = new ArrayList<>();
        Set<String> visited = new HashSet<>();
        int maxSteps = Math.max(20, steps.size() * 3);

        for (int count = 0; count < maxSteps; count++) {
            if (isTerminal(currentId)) {
                return Map.of("success", !"error".equalsIgnoreCase(currentId),
                        "workflowId", workflowId, "finalStep", currentId, "steps", history);
            }
            if (!visited.add(currentId)) {
                return Map.of("success", false, "workflowId", workflowId,
                        "error", "Workflow loop detected at step " + currentId, "steps", history);
            }

            Map<?, ?> step = byId.get(currentId);
            if (step == null) return Map.of("success", false, "error", "Unknown step: " + currentId, "steps", history);

            String apiName = String.valueOf(step.get("apiname"));
            String prompt = String.valueOf(step.get("prompt"));
            Map<String, Object> stepResult = new LinkedHashMap<>();
            stepResult.put("stepId", currentId);
            stepResult.put("apiname", apiName);

            try {
                Object output;
                if ("processStructuredRequest".equalsIgnoreCase(apiName)
                        || "ai".equalsIgnoreCase(apiName)
                        || "ownAi".equalsIgnoreCase(apiName)) {
                    output = aiClient.askAi(prompt);
                } else {
                    String xml = extractXml(prompt);
                    if (xml == null) throw new IllegalArgumentException(
                            "Step " + currentId + ": no XML found in prompt for OMS API " + apiName);
                    output = omsInterop.postInterop(apiName, xml, null, null, null, null, null);
                    if (output instanceof Map<?, ?> m && Boolean.FALSE.equals(m.get("success"))) {
                        throw new IllegalStateException(String.valueOf(m.get("error")));
                    }
                }

                stepResult.put("success", true);
                stepResult.put("output", output);
                history.add(stepResult);
                currentId = route(step.get("onSuccess"), "end");
            } catch (Exception ex) {
                stepResult.put("success", false);
                stepResult.put("error", ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage());
                history.add(stepResult);
                currentId = route(step.get("onError"), "error");
            }
        }

        return Map.of("success", false, "workflowId", workflowId,
                "error", "Maximum workflow step count exceeded", "steps", history);
    }

    private String route(Object routeObject, String fallback) {
        if (routeObject instanceof Map<?, ?> route && route.get("gotoStep") != null) {
            return String.valueOf(route.get("gotoStep"));
        }
        return fallback;
    }

    private boolean isTerminal(String id) {
        return Set.of("end", "error", "finish", "stop", "c").contains(id.toLowerCase(Locale.ROOT));
    }

    private String extractXml(String prompt) {
        if (prompt == null) return null;
        int start = prompt.indexOf('<');
        int end = prompt.lastIndexOf('>');
        if (start < 0 || end <= start) return null;
        return prompt.substring(start, end + 1).trim();
    }
}
