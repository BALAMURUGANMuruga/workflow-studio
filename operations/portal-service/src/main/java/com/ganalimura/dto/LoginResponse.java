package com.ganalimura.dto;

public record LoginResponse(
    String token,
    String username,
    String message
) {}