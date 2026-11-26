package com.ganalimura.reprocess.config;


import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.annotation.PostConstruct;

import org.springframework.stereotype.Component;

import java.io.InputStream;
import java.util.List;
import java.util.Map;

@Component
public class ErrorConfigLoader {

    private Map<String, List<Map<String, Object>>> config;

    @PostConstruct
    @SuppressWarnings("unchecked")
    public void load() throws Exception {

        ObjectMapper mapper = new ObjectMapper();

        InputStream is = getClass()
                .getClassLoader()
                .getResourceAsStream("error-config.json");

        config = mapper.readValue(is, Map.class);
    }

    public List<Map<String, Object>> getScenarios(String errorCode) {
        return config.getOrDefault(errorCode, List.of());
    }

    public Map<String, List<Map<String, Object>>> getConfig() {
        return config;
    }
}