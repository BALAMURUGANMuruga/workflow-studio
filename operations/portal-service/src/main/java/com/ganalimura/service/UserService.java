package com.ganalimura.service;


import java.util.List;

import org.springframework.stereotype.Service;

import com.ganalimura.entity.User;
import com.ganalimura.repository.UserRepository;



@Service
public class UserService {

	private final UserRepository repository;

    public UserService(UserRepository repository) {
        this.repository = repository;
    }

    public List<User> getAllUsers() {
        return repository.findAll();
    }

    public User getUserById(String id) {
        return repository.findById(id)
                .orElseThrow(() ->
                        new RuntimeException("User not found: " + id));
    }

    public User createUser(User user) {
        return repository.save(user);
    }

    public User updateUser(String id, User request) {

        User existingUser = repository.findById(id)
                .orElseThrow(() ->
                        new RuntimeException("User not found: " + id)
                );

        existingUser.setName(request.getName());
        existingUser.setUrl(request.getUrl());

        // Only update password when a new password is provided
        if (request.getPassword() != null
                && !request.getPassword().isBlank()) {

            existingUser.setPassword(request.getPassword());
        }

        return repository.save(existingUser);
    }

    public void deleteUser(String id) {

        if (!repository.existsById(id)) {
            throw new RuntimeException("User not found: " + id);
        }

        repository.deleteById(id);
    }
}