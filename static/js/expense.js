document.addEventListener('DOMContentLoaded', function () {
    // DOM Elements
    const expenseForm = document.querySelector('form[action*="report_expense"]');
    const expenseDateInput = document.querySelector('input[name="expense_date"]');
    const expenseAmountInput = document.querySelector('input[name="expense_amount"]');
    const expenseContactSelect = document.querySelector('select[name="expense_contact"]');
    const newContactInput = document.querySelector('input[name="new_contact"]');
    const expenseAccountCodeSelect = document.querySelector('select[name="expense_account_code"]');
    const expenseDescriptionInput = document.querySelector('textarea[name="expense_description"]');
    const expenseReceiptInput = document.querySelector('input[name="files"]');
    const uploadArea = document.querySelector('.upload-area');
    const addButton = document.querySelector('button[type="submit"]');
    const totalExpenseSpan = document.querySelector('.bg-white .text-gray-900.font-semibold');

    // Validation state
    let isFormValid = false;

    // Initialize form
    initializeForm();

    // Event listeners
    if (expenseForm) {
        expenseForm.addEventListener('submit', handleExpenseSubmission);
    }

    if (expenseAmountInput) {
        expenseAmountInput.addEventListener('input', validateExpenseAmount);
        expenseAmountInput.addEventListener('blur', validateExpenseAmount);
    }

    if (expenseContactSelect) {
        expenseContactSelect.addEventListener('change', handleContactSelection);
    }

    if (expenseAccountCodeSelect) {
        expenseAccountCodeSelect.addEventListener('change', validateAccountCode);
    }

    if (expenseReceiptInput) {
        expenseReceiptInput.addEventListener('change', handleFileUpload);
    }

    // Initialize form with current date
    function initializeForm() {
        if (expenseDateInput) {
            const today = new Date().toISOString().split('T')[0];
            expenseDateInput.value = today;
        }
        
        // Set initial validation state
        validateForm();
    }

    // Handle contact selection
    function handleContactSelection() {
        const newContactSection = document.getElementById('newContactSection');
        if (this.value === 'add_new') {
            newContactSection.classList.remove('hidden');
            newContactInput.required = true;
        } else {
            newContactSection.classList.add('hidden');
            newContactInput.required = false;
            newContactInput.value = '';
        }
        validateForm();
    }

    // Handle file upload
    function handleFileUpload() {
        if (this.files.length > 0) {
            let fileList = '';
            let totalSize = 0;
            
            Array.from(this.files).forEach((file, index) => {
                const fileName = file.name;
                const fileSize = file.size;
                const maxSize = 10 * 1024 * 1024; // 10MB

                // Validate file size
                if (fileSize > maxSize) {
                    alert(`File ${fileName} is too large. File size must be less than 10MB`);
                    this.value = '';
                    resetUploadArea();
                    return;
                }
                
                // Validate file type
                const allowedTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png'];
                if (!allowedTypes.includes(file.type)) {
                    alert(`File ${fileName} is not allowed. Only PDF, JPEG, and PNG files are allowed`);
                    this.value = '';
                    resetUploadArea();
                    return;
                }
                
                totalSize += fileSize;
                fileList += `<div class="text-green-600 font-medium">✓ ${fileName}</div>`;
            });
            
            // Update upload area display
            if (uploadArea) {
                uploadArea.innerHTML = `
                    ${fileList}
                    <div class="text-sm text-gray-500">${this.files.length} file(s) uploaded successfully</div>
                `;
            }
        } else {
            resetUploadArea();
        }
        validateForm();
    }

    // Reset upload area
    function resetUploadArea() {
        if (uploadArea) {
            uploadArea.innerHTML = `
                <div class="upload-icon">
                    <i class="ri-upload-line"></i>
                </div>
                <div class="text-gray-600 font-medium">Click to upload</div>
                <div class="file-types">PDF, JPEG, PNG (Max 10MB)</div>
            `;
        }
    }

    // Validate expense amount (without calling validateForm to avoid recursion)
    function validateExpenseAmount() {
        const amount = parseFloat(this.value) || 0;
        let isValid = true;
        let errorMessage = '';

        if (!this.value || this.value.trim() === '') {
            isValid = false;
            errorMessage = 'Amount is required';
        } else if (amount <= 0) {
            isValid = false;
            errorMessage = 'Amount must be greater than 0';
        } else if (amount > 999999.99) {
            isValid = false;
            errorMessage = 'Amount cannot exceed $999,999.99';
        }

        // Update visual feedback
        if (isValid) {
            this.classList.remove('is-invalid');
            this.classList.add('is-valid');
            removeErrorMessage(this);
        } else {
            this.classList.remove('is-valid');
            this.classList.add('is-invalid');
            showErrorMessage(this, errorMessage);
        }

        // Call validateForm after a short delay to avoid immediate recursion
        setTimeout(() => validateForm(), 0);
        return isValid;
    }

    // Validate account code (without calling validateForm to avoid recursion)
    function validateAccountCode() {
        const accountCode = this.value;
        let isValid = true;
        let errorMessage = '';

        if (!accountCode || accountCode.trim() === '') {
            isValid = false;
            errorMessage = 'Account code is required';
        }

        // Update visual feedback
        if (isValid) {
            this.classList.remove('is-invalid');
            this.classList.add('is-valid');
            removeErrorMessage(this);
        } else {
            this.classList.remove('is-valid');
            this.classList.add('is-invalid');
            showErrorMessage(this, errorMessage);
        }

        // Call validateForm after a short delay to avoid immediate recursion
        setTimeout(() => validateForm(), 0);
        return isValid;
    }

    // Validate expense date
    function validateExpenseDate() {
        if (!expenseDateInput) return true;
        
        const selectedDate = new Date(expenseDateInput.value);
        const today = new Date();
        today.setHours(23, 59, 59, 999); // End of today to allow today's date
        
        let isValid = true;
        let errorMessage = '';

        if (!expenseDateInput.value) {
            isValid = false;
            errorMessage = 'Date is required';
        } else if (selectedDate > today) {
            isValid = false;
            errorMessage = 'Date cannot be in the future';
        }

        // Update visual feedback
        if (isValid) {
            expenseDateInput.classList.remove('is-invalid');
            expenseDateInput.classList.add('is-valid');
            removeErrorMessage(expenseDateInput);
        } else {
            expenseDateInput.classList.remove('is-valid');
            expenseDateInput.classList.add('is-invalid');
            showErrorMessage(expenseDateInput, errorMessage);
        }

        return isValid;
    }

    // Validate contact selection
    function validateContact() {
        if (!expenseContactSelect) return true;
        
        const contact = expenseContactSelect.value;
        let isValid = true;
        let errorMessage = '';

        if (!contact || contact.trim() === '') {
            isValid = false;
            errorMessage = 'Contact is required';
        } else if (contact === 'add_new' && (!newContactInput || !newContactInput.value.trim())) {
            isValid = false;
            errorMessage = 'New contact name is required';
        }

        // Update visual feedback
        if (isValid) {
            expenseContactSelect.classList.remove('is-invalid');
            expenseContactSelect.classList.add('is-valid');
            removeErrorMessage(expenseContactSelect);
            
            if (newContactInput && newContactInput.value.trim()) {
                newContactInput.classList.remove('is-invalid');
                newContactInput.classList.add('is-valid');
                removeErrorMessage(newContactInput);
            }
        } else {
            expenseContactSelect.classList.remove('is-valid');
            expenseContactSelect.classList.add('is-invalid');
            showErrorMessage(expenseContactSelect, errorMessage);
            
            if (newContactInput && contact === 'add_new') {
                newContactInput.classList.remove('is-valid');
                newContactInput.classList.add('is-invalid');
                showErrorMessage(newContactInput, 'New contact name is required');
            }
        }

        return isValid;
    }

    // Show error message
    function showErrorMessage(element, message) {
        removeErrorMessage(element);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'text-red-500 text-sm mt-1';
        errorDiv.textContent = message;
        element.parentNode.appendChild(errorDiv);
    }

    // Remove error message
    function removeErrorMessage(element) {
        const existingError = element.parentNode.querySelector('.text-red-500');
        if (existingError) {
            existingError.remove();
        }
    }

    // Validate entire form
    function validateForm() {
        // Get current values for validation
        const amountValue = expenseAmountInput ? expenseAmountInput.value : '';
        const accountCodeValue = expenseAccountCodeSelect ? expenseAccountCodeSelect.value : '';
        
        // Validate amount
        let amountValid = true;
        if (expenseAmountInput) {
            const amount = parseFloat(amountValue) || 0;
            if (!amountValue || amountValue.trim() === '') {
                amountValid = false;
            } else if (amount <= 0) {
                amountValid = false;
            } else if (amount > 999999.99) {
                amountValid = false;
            }
        }
        
        // Validate account code
        let accountValid = true;
        if (expenseAccountCodeSelect) {
            if (!accountCodeValue || accountCodeValue.trim() === '') {
                accountValid = false;
            }
        }
        
        // Validate file upload
        let fileValid = true;
        if (expenseReceiptInput) {
            if (!expenseReceiptInput.files || expenseReceiptInput.files.length === 0) {
                fileValid = false;
                // Show error on upload area
                if (uploadArea) {
                    uploadArea.classList.add('border-red-300');
                    uploadArea.classList.remove('border-gray-300');
                }
            } else {
                // Remove error styling
                if (uploadArea) {
                    uploadArea.classList.remove('border-red-300');
                    uploadArea.classList.add('border-gray-300');
                }
            }
        }
        
        const dateValid = validateExpenseDate();
        const contactValid = validateContact();

        isFormValid = amountValid && dateValid && accountValid && contactValid && fileValid;

        // Update button state
        if (addButton) {
            addButton.disabled = !isFormValid;
            addButton.classList.toggle('opacity-50', !isFormValid);
            addButton.classList.toggle('cursor-not-allowed', !isFormValid);
        }

        return isFormValid;
    }

    // Handle expense form submission
    async function handleExpenseSubmission(event) {
        event.preventDefault();

        if (!validateForm()) {
            alert('Please fix the validation errors before submitting.');
            return;
        }

        // Disable submit button to prevent double submission
        if (addButton) {
            addButton.disabled = true;
            addButton.textContent = 'Adding...';
        }

        try {
            const formData = new FormData(expenseForm);
            
            // Add CSRF token if not present
            if (!formData.has('csrf_token')) {
                const csrfToken = document.querySelector('input[name="csrf_token"]');
                if (csrfToken) {
                    formData.append('csrf_token', csrfToken.value);
                }
            }

            // Handle file upload properly
            const fileInput = document.querySelector('input[name="files"]');
            
            if (fileInput && fileInput.files.length > 0) {
                // Clear any existing file data to avoid duplicates
                formData.delete('files');
                
                // Add all files to form data
                Array.from(fileInput.files).forEach((file) => {
                    formData.append('files', file, file.name);
                });
            }

            const response = await fetch(expenseForm.action, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'include',
            });

            if (response.ok) {
                const data = await response.json();
                if (data.status === 'success') {
                    alert(data.message || 'Expense added successfully!');
                    if (data.redirect_url) {
                        window.location.href = data.redirect_url;
                    } else {
                        // Fallback redirect to deposit page
                        window.location.href = '/report/deposit';
                    }
                } else {
                    alert(`Error: ${data.message || 'An unknown error occurred.'}`);
                }
            } else {
                const errorText = await response.text();
                console.error("Server error response:", errorText);
                alert("Submission failed. Please try again.");
            }
        } catch (error) {
            console.error("Unexpected error during expense submission:", error);
            alert("An unexpected error occurred. Please try again.");
        } finally {
            // Re-enable submit button
            if (addButton) {
                addButton.disabled = false;
                addButton.textContent = 'Add';
            }
        }
    }

    // Update total expense display
    function updateTotalExpense() {
        if (totalExpenseSpan) {
            // Get the amount being entered in the form
            const newAmount = parseFloat(expenseAmountInput.value) || 0;
            
            // Show only the amount being entered, not accumulated with existing expenses
            totalExpenseSpan.textContent = `$${newAmount.toFixed(2)}`;
        }
    }

    // Add event listener for amount changes to update total
    if (expenseAmountInput) {
        expenseAmountInput.addEventListener('input', updateTotalExpense);
    }

    // Reset total when form is cleared
    function resetTotalExpense() {
        if (totalExpenseSpan) {
            totalExpenseSpan.textContent = '$0.00';
        }
    }

    // Add event listener to reset total when amount is cleared
    if (expenseAmountInput) {
        expenseAmountInput.addEventListener('input', function() {
            if (this.value === '' || parseFloat(this.value) === 0) {
                resetTotalExpense();
            } else {
                updateTotalExpense();
            }
        });
    }

    // Initial validation
    validateForm();
});
