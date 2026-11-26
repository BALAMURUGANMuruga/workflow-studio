package com.ganalimura.reprocess.dto;



public class ProcessStep {

    private String message;

    // 🔥 NEW FIELDS
    private String inputXml;
    private String errorXml;

    // ✅ getters & setters

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public String getInputXml() {
        return inputXml;
    }

    public void setInputXml(String inputXml) {
        this.inputXml = inputXml;
    }

    public String getErrorXml() {
        return errorXml;
    }

    public void setErrorXml(String errorXml) {
        this.errorXml = errorXml;
    }
}