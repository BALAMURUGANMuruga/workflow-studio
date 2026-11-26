
package com.ganalimura.service;

import com.ganalimura.dto.ForgotPasswordRequest;
import com.ganalimura.dto.ResetPasswordRequest;
import com.ganalimura.entity.AppUser;
import com.ganalimura.entity.PasswordResetOtp;
import com.ganalimura.repository.AppUserRepository;
import com.ganalimura.repository.PasswordResetOtpRepository;

import org.springframework.http.HttpStatus;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.beans.factory.annotation.Value;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Map;

@Service
public class PasswordResetService {

    private final AppUserRepository userRepository;
    private final PasswordResetOtpRepository otpRepository;
    private final PasswordEncoder passwordEncoder;
    private final JavaMailSender mailSender;
    private final SecureRandom secureRandom = new SecureRandom();

    @Value("${app.mail.from:}")
    private String fromEmail;

    public PasswordResetService(
            AppUserRepository userRepository,
            PasswordResetOtpRepository otpRepository,
            PasswordEncoder passwordEncoder,
            JavaMailSender mailSender) {
        this.userRepository = userRepository;
        this.otpRepository = otpRepository;
        this.passwordEncoder = passwordEncoder;
        this.mailSender = mailSender;
    }

    @Transactional
    public Map<String, String> requestOtp(
            ForgotPasswordRequest request) {

        String email = request.email().trim().toLowerCase();

        // Use the same response for registered and unregistered emails.
        var user = userRepository.findByEmailIgnoreCase(email);

        if (user.isPresent()) {
            String otp = String.format(
                    "%06d", secureRandom.nextInt(1_000_000));

            String otpHash = passwordEncoder.encode(otp);

            otpRepository.deleteByEmailIgnoreCase(email);

            otpRepository.save(new PasswordResetOtp(
                    email,
                    otpHash,
                    LocalDateTime.now().plusMinutes(10)));

            SimpleMailMessage message = new SimpleMailMessage();
            message.setFrom(fromEmail);
            message.setTo(email);
            message.setSubject("Ganalimura password reset code");
            message.setText(
                    "Your password reset code is: " + otp
                    + "\n\nThis code expires in 10 minutes."
                    + "\nIf you did not request this, ignore this email.");

            mailSender.send(message);
        }

        return Map.of(
                "message",
                "If this email is registered, a reset code will be sent.");
    }

    @Transactional
    public Map<String, String> resetPassword(
            ResetPasswordRequest request) {

        String email = request.email().trim().toLowerCase();

        PasswordResetOtp storedOtp = otpRepository
                .findByEmailIgnoreCase(email)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.BAD_REQUEST,
                        "Invalid or expired reset code"));

        if (LocalDateTime.now().isAfter(storedOtp.getExpiresAt())
                || !passwordEncoder.matches(
                        request.otp(), storedOtp.getOtpHash())) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Invalid or expired reset code");
        }

        AppUser user = userRepository.findByEmailIgnoreCase(email)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.BAD_REQUEST,
                        "Invalid or expired reset code"));

        user.setPasswordHash(
                passwordEncoder.encode(request.newPassword()));

        userRepository.save(user);
        otpRepository.deleteByEmailIgnoreCase(email);

        return Map.of(
                "message",
                "Password reset successfully. You can sign in now.");
    }
}
