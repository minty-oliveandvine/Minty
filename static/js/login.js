document.addEventListener('DOMContentLoaded', function () {
    // Toggle password visibility
    const togglePassword = document.getElementById('togglePassword');
    const password = document.getElementById('password');
    togglePassword.addEventListener('click', function () {
        const type = password.getAttribute('type') === 'password' ? 'text' : 'password';
        password.setAttribute('type', type);
        // Toggle eye icon
        const eyeIcon = togglePassword.querySelector('i');
        if (type === 'password') {
            eyeIcon.classList.remove('ri-eye-off-line');
            eyeIcon.classList.add('ri-eye-line');
        } else {
            eyeIcon.classList.remove('ri-eye-line');
            eyeIcon.classList.add('ri-eye-off-line');
        }
    });
});
document.addEventListener('DOMContentLoaded', function () {
    // Form validation
    const loginForm = document.getElementById('loginForm');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const usernameError = document.getElementById('usernameError');
    const passwordError = document.getElementById('passwordError');
    const loginText = document.getElementById('loginText');
    const loginSpinner = document.getElementById('loginSpinner');
    loginForm.addEventListener('submit', function (e) {
        e.preventDefault();
        // Reset errors
        usernameError.classList.add('hidden');
        passwordError.classList.add('hidden');
        let isValid = true;
        // Validate username
        if (usernameInput.value.trim() === '') {
            usernameError.textContent = 'Username is required';
            usernameError.classList.remove('hidden');
            isValid = false;
        }
        if (passwordInput.value.length < 8) {
            passwordError.textContent = 'Password must be at least 8 characters';
            passwordInput.classList.add('input-error')
            passwordError.classList.remove('hidden');
            isValid = false;
        }else{
            passwordInput.classList.remove('input-error')
            isValid = true
        }
        if (isValid) {
            // Show loading state
            loginText.classList.add('hidden');
            loginSpinner.classList.remove('hidden');
            // Simulate login (replace with actual login logic)
            setTimeout(function () {
                loginText.classList.remove('hidden');
                loginSpinner.classList.add('hidden');
                loginForm.submit()
                // Show success message
                document.getElementById('successTitle').textContent = 'Login Successful!';
                document.getElementById('successMessage').textContent = 'Redirecting to dashboard...';
                document.getElementById('successModal').classList.remove('hidden');
                // Redirect after a delay (in a real app)
                setTimeout(function () {
                    // window.location.href = '/dashboard';
                    document.getElementById('successModal').classList.add('hidden');
                }, 2000);
            }, 1500);
        }
    });
});
document.addEventListener('DOMContentLoaded', function () {
    // Xero login button
    const xeroLoginBtn = document.getElementById('xeroLoginBtn');
    xeroLoginBtn.addEventListener('click', function () {
        // In a real app, this would redirect to Xero OAuth
        document.getElementById('successTitle').textContent = 'Redirecting to Xero';
        document.getElementById('successMessage').textContent = 'You will be redirected to Xero for authentication.';
        document.getElementById('successModal').classList.remove('hidden');
        setTimeout(function () {
            document.getElementById('successModal').classList.add('hidden');
            window.location.href = '/xero_auth';
        }, 2000);
    });
});
document.addEventListener('DOMContentLoaded', function () {
    // Forgot password
    const forgotPasswordLink = document.getElementById('forgotPasswordLink');
    const resetPasswordModal = document.getElementById('resetPasswordModal');
    const closeResetModal = document.getElementById('closeResetModal');
    const resetPasswordForm = document.getElementById('resetPasswordForm');
    const resetEmailInput = document.getElementById('resetEmail');
    const resetEmailError = document.getElementById('resetEmailError');
    const resetText = document.getElementById('resetText');
    const resetSpinner = document.getElementById('resetSpinner');
    forgotPasswordLink.addEventListener('click', function (e) {
        e.preventDefault();
        resetPasswordModal.classList.remove('hidden');
    });
    closeResetModal.addEventListener('click', function () {
        resetPasswordModal.classList.add('hidden');
    });
    resetPasswordForm.addEventListener('submit', function (e) {
        e.preventDefault();
        resetEmailError.classList.add('hidden');
        // Simple email validation 
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(resetEmailInput.value)) {
            resetEmailError.textContent = 'Please enter a valid email address';
            resetEmailError.classList.remove('hidden');
            return;
        }
        // Show loading state
        resetText.classList.add('hidden');
        resetSpinner.classList.remove('hidden');
        // Simulate sending reset email
        setTimeout(function () {
            resetText.classList.remove('hidden');
            resetSpinner.classList.add('hidden');
            resetPasswordModal.classList.add('hidden');
            resetPasswordForm.submit()
            // Show success message
            document.getElementById('successTitle').textContent = 'Reset Link Sent!';
            document.getElementById('successMessage').textContent = `We've sent a password reset link to ${resetEmailInput.value}. Please check your inbox.`;
            document.getElementById('successModal').classList.remove('hidden');
        }, 1500);
    });
});
document.addEventListener('DOMContentLoaded', function () {
    // Success modal close button
    const closeSuccessModal = document.getElementById('closeSuccessModal');
    closeSuccessModal.addEventListener('click', function () {
        document.getElementById('successModal').classList.add('hidden');
    });

});