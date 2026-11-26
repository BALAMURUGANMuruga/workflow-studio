
package com.ganalimura.service;

import com.ganalimura.dto.RegisterRequest;
import com.ganalimura.entity.AppUser;
import com.ganalimura.repository.AppUserRepository;

import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

@Service
public class RegistrationService {

    private final AppUserRepository repository;
    private final PasswordEncoder passwordEncoder;

    public RegistrationService(
            AppUserRepository repository,
            PasswordEncoder passwordEncoder) {
        this.repository = repository;
        this.passwordEncoder = passwordEncoder;
    }

    @Transactional
    public Map<String, String> register(RegisterRequest request) {

        String username = request.username().trim();
        String email = request.email().trim();

        if (repository.existsByUsernameIgnoreCase(username)) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "Username is already in use");
        }

        if (repository.existsByEmailIgnoreCase(email)) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "Email is already registered");
        }

        AppUser user = new AppUser();
        user.setUsername(username);
        user.setEmail(email);
        user.setPasswordHash(
                passwordEncoder.encode(request.password()));
        user.setEnabled(true);

        repository.save(user);

        return Map.of(
                "message",
                "Account created successfully. Please sign in.");
    }
}
