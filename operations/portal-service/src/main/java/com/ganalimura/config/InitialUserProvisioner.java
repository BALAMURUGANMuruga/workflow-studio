package com.ganalimura.config;

import org.springframework.boot.CommandLineRunner;
import org.springframework.core.env.Environment;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

import com.ganalimura.entity.AppUser;
import com.ganalimura.repository.AppUserRepository;


@Component
public class InitialUserProvisioner implements CommandLineRunner {

    private final AppUserRepository repository;
    private final PasswordEncoder passwordEncoder;

    public InitialUserProvisioner(
            AppUserRepository repository,
            PasswordEncoder passwordEncoder) {
        this.repository = repository;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    public void run(String... args) {
        String username = System.getenv("BOOTSTRAP_USERNAME");
        String password = System.getenv("BOOTSTRAP_PASSWORD");

        if (username == null || username.isBlank()
                || password == null || password.isBlank()) {
            System.out.println("Bootstrap user variables are missing.");
            return;
        }

        if (repository.findByUsernameIgnoreCase(username).isEmpty()) {
            AppUser user = new AppUser();
            user.setUsername(username);
            user.setPasswordHash(passwordEncoder.encode(password));
            user.setEnabled(true);
            repository.save(user);

            System.out.println("Initial login account created.");
        } else {
            System.out.println("Bootstrap user already exists.");
        }
    }
}