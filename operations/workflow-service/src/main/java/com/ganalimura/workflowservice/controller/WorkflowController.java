package com.ganalimura.workflowservice.controller;

import com.ganalimura.workflowservice.workflow.WorkflowExecutionService;
import com.ganalimura.workflowservice.workflow.WorkflowFileService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.util.Map;

@RestController
@RequestMapping("/api/workflows")
public class WorkflowController {
    private final WorkflowFileService files;
    private final WorkflowExecutionService execution;

    public WorkflowController(WorkflowFileService files, WorkflowExecutionService execution) {
        this.files = files;
        this.execution = execution;
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> save(@RequestBody Map<String, Object> workflow) throws IOException {
        return ResponseEntity.status(HttpStatus.CREATED).body(files.save(workflow));
    }

    @GetMapping
    public Map<String, Object> list() throws IOException {
        return Map.of("workflows", files.list());
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String id) throws IOException {
        return files.read(id);
    }

    @PostMapping("/{id}/run")
    public Map<String, Object> run(@PathVariable String id) throws IOException {
        return execution.run(id);
    }

    @ExceptionHandler({IllegalArgumentException.class})
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException ex) {
        return ResponseEntity.badRequest().body(Map.of("error", ex.getMessage()));
    }

    @ExceptionHandler({java.nio.file.NoSuchFileException.class})
    public ResponseEntity<Map<String, String>> notFound(Exception ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", "Workflow not found"));
    }
}
