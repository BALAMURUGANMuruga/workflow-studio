package com.ganalimura.service;

import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import com.ganalimura.dto.LoginRequest;
import com.ganalimura.dto.LoginResponse;
import com.ganalimura.repository.AppUserRepository;
import com.ganalimura.security.JwtService;

@Service
public class AuthService {

    private final AppUserRepository repository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

    public AuthService(
            AppUserRepository repository,
            PasswordEncoder passwordEncoder,
            JwtService jwtService) {

        this.repository = repository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
    }

    public LoginResponse login(LoginRequest request) {

        var user = repository
            .findByUsernameIgnoreCase(request.username().trim())
            .orElseThrow(() ->
                new BadCredentialsException("Invalid credentials"));

        if (!user.isEnabled()
                || !passwordEncoder.matches(
                    request.password(),
                    user.getPasswordHash())) {

            throw new BadCredentialsException("Invalid credentials");
        }

        String token = jwtService.generateToken(user.getUsername());

        return new LoginResponse(
            token,
            user.getUsername(),
            "Login successful"
        );
    }
}