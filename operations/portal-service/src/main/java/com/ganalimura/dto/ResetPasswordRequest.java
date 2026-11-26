
package com.ganalimura.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record ResetPasswordRequest(
    @NotBlank @Email String email,

    @NotBlank
    @Pattern(regexp = "\\d{6}", message = "OTP must contain six digits")
    String otp,

    @NotBlank
    @Size(min = 12, max = 72,
          message = "Password must contain 8 to 15 characters")
    String newPassword
) {}
