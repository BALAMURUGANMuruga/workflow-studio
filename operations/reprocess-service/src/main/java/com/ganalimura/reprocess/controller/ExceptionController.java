// Expose Spring HTTP endpoints for reviewing and reprocessing integration exceptions.
package com.ganalimura.reprocess.controller;

import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import com.ganalimura.reprocess.service.ExceptionService;

@CrossOrigin(origins = "*")
@RestController
@RequestMapping("/oms")
public class ExceptionController {

    @Autowired
    private ExceptionService exceptionService;

    // ============================================
    // 🎮 CONTROL APIs (Pause / Resume / Stop)
    // ============================================

    @PostMapping("/control")
    public ResponseEntity<String> control(@RequestBody Map<String, String> req) {

        String action = req.get("action");

        switch (action) {
            case "pause":
                exceptionService.pause();
                break;

            case "resume":
                exceptionService.resume();
                break;

            case "stop":
                exceptionService.stop();
                break;

            default:
                return ResponseEntity.badRequest().body("Invalid action");
        }

        return ResponseEntity.ok("Action executed: " + action);
    }

    // ============================================
    // 📋 DROPDOWN DATA
    // ============================================

    @GetMapping("/exception-codes")
    public ResponseEntity<?> getExceptionCodes() {
        return ResponseEntity.ok(exceptionService.getExceptionCodes());
    }
}