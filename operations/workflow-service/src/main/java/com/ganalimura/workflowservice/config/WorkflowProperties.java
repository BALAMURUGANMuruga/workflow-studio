package com.ganalimura.workflowservice.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "myai.workflows")
public class WorkflowProperties {
    private String directory = "C:/test/MyAI/workflows";
    public String getDirectory() { return directory; }
    public void setDirectory(String directory) { this.directory = directory; }
}
