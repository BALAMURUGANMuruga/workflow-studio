package com.ganalimura.dto;

import java.util.List;

public class ProcessStatusResponse {

    private List<ProcessStep> steps;

    public List<ProcessStep> getSteps() {
        return steps;
    }

    public void setSteps(List<ProcessStep> steps) {
        this.steps = steps;
    }
}