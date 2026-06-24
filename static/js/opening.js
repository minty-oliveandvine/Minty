document.addEventListener('DOMContentLoaded', function () {
    // DOM Elements - synced with main scripts.js and index.html naming
    const openingDrawerInput = document.getElementById('openingDrawer');
    const cashAdditionInput = document.getElementById('additiontocashbalance');
    const adjustedOpeningBalanceInput = document.getElementById('adjustedOpeningBalance');
    const transactionDateInput = document.getElementById('transaction_date');
    const nextTransactionDate = transactionDateInput.dataset.nextTransactionDate; // Assuming the backend sets this data attribute
    const isFirstReport = transactionDateInput.dataset.firstReport === 'true';
    const finalAdjustedOpeningBalanceDisplay = document.getElementById('final_adjusted_opening_balance');
    const withdrawalFromRadios = document.querySelectorAll('input[name="withdrawalFrom"]');
    const bankAccountSelect = document.querySelector('select[name="bank_account"]');
    const form = document.querySelector('form');

    

    console.log("Next Transaction Date:", nextTransactionDate);
    console.log("Is First Report:", isFirstReport);

    // Flatpickr for Transaction Date - synced with main scripts.js
    if (isFirstReport === true) {
        flatpickr("#transaction_date", {
            dateFormat: "Y-m-d",
            defaultDate: transactionDateInput.value,
            minDate: transactionDateInput.value, // The starting date
        });
    } else {
        transactionDateInput.readOnly = true;
        flatpickr("#transaction_date", {
            dateFormat: "Y-m-d",
            defaultDate: transactionDateInput.value,
            clickOpens: false, // Disable calendar interaction
            disableMobile: true, // Ensure no picker appears on mobile
        });
    }

    // Disable manual interaction with readonly transaction date
    transactionDateInput.addEventListener('focus', (e) => {
        if (transactionDateInput.readOnly) e.preventDefault();
    });

    if (transactionDateInput && nextTransactionDate) {
        transactionDateInput.value = nextTransactionDate; 
        transactionDateInput.readOnly = true; 
    } else {
        console.error('Next transaction date is undefined!');
    }

    // Function to add fields to FormData, avoiding duplicates (synced with main scripts.js)
    function addFieldToFormData(formData, key, value) {
        if (!formData.has(key) && value) {
            formData.append(key, value);
        }
    }

    // Validation and calculation functions synced with main scripts.js logic
    function updateAdjustedOpeningBalance() {
        const openingBalance = parseFloat(openingDrawerInput.value || 0);
        const cashAddition = parseFloat(cashAdditionInput.value || 0);
        const adjustedBalance = openingBalance + cashAddition;
        
        // Update both the input field and display
        adjustedOpeningBalanceInput.value = adjustedBalance.toFixed(2);
        if (finalAdjustedOpeningBalanceDisplay) {
            finalAdjustedOpeningBalanceDisplay.innerText = adjustedBalance.toFixed(2);
        }
        
        console.log('Opening Balance:', openingBalance);
        console.log('Cash Addition:', cashAddition);
        console.log('Adjusted Opening Balance:', adjustedBalance);
    }

    function validateForm() {
        let isValid = true;
        
        // Validate required fields
        const requiredFields = document.querySelectorAll("input[required], select[required]");
        requiredFields.forEach((field) => {
            if (!field.value || field.value.trim() === "") {
                field.classList.add("is-invalid");
                isValid = false;
            } else {
                field.classList.remove("is-invalid");
            }
        });

        // Validate cash addition is positive
        const cashAddition = parseFloat(cashAdditionInput.value || 0);
        if (cashAddition < 0) {
            cashAdditionInput.classList.add("is-invalid");
            isValid = false;
        } else {
            cashAdditionInput.classList.remove("is-invalid");
        }

        // Validate transaction date is set
        if (!transactionDateInput.value) {
            transactionDateInput.classList.add("is-invalid");
            isValid = false;
        } else {
            transactionDateInput.classList.remove("is-invalid");
        }

        // Validate withdrawal source is selected
        const withdrawalSelected = Array.from(withdrawalFromRadios).some(radio => radio.checked);
        if (!withdrawalSelected) {
            withdrawalFromRadios.forEach(radio => {
                radio.closest('label').classList.add("is-invalid");
            });
            isValid = false;
        } else {
            withdrawalFromRadios.forEach(radio => {
                radio.closest('label').classList.remove("is-invalid");
            });
        }

        // Validate bank account is selected
        if (!bankAccountSelect.value) {
            bankAccountSelect.classList.add("is-invalid");
            isValid = false;
        } else {
            bankAccountSelect.classList.remove("is-invalid");
        }

        console.log("Opening form validation result:", isValid);
        return isValid;
    }

    // Form submission handler synced with main scripts.js pattern
    async function submitOpeningForm(event) {
        event.preventDefault();
        
        if (!validateForm()) {
            alert("Please fill in all required fields and ensure valid values.");
            return;
        }

        const formData = new FormData(form);
        
        // Add necessary fields to form data using the same pattern as main scripts.js
        const csrfToken = document.querySelector('input[name="csrf_token"]');
        addFieldToFormData(formData, 'csrf_token', csrfToken ? csrfToken.value : '');
        addFieldToFormData(formData, 'opening_balance', openingDrawerInput.value || '0');
        addFieldToFormData(formData, 'cash_addition', cashAdditionInput.value || '0');
        addFieldToFormData(formData, 'transaction_date', transactionDateInput.value || '');
        addFieldToFormData(formData, 'adjusted_opening_balance', adjustedOpeningBalanceInput.value || '0');
        
        // Handle withdrawal source selection with better error handling
        const selectedWithdrawal = Array.from(withdrawalFromRadios).find(radio => radio.checked);
        const withdrawalValue = selectedWithdrawal ? selectedWithdrawal.value : '';
        addFieldToFormData(formData, 'withdrawalFrom', withdrawalValue);
        
        addFieldToFormData(formData, 'bank_account', bankAccountSelect.value || '');
        
        console.log("Opening form data prepared:", [...formData.entries()]);

        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'include',
            });

            console.log("Opening form response status:", response.status);

            if (response.ok) {
                const data = await response.json();
                if (data.status === 'success') {
                    alert(data.message || 'Opening entry saved successfully!');
                    if (data.redirect_url) {
                        window.location.href = data.redirect_url;
                    } else {
                        // Fallback redirect to sales page
                        window.location.href = '/report/sale';
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
            console.error("Unexpected error during opening form submission:", error);
            alert("An unexpected error occurred. Please try again.");
        }
    }

    // Event listeners
    cashAdditionInput.addEventListener('input', updateAdjustedOpeningBalance);
    cashAdditionInput.addEventListener('change', updateAdjustedOpeningBalance);
    
    // Form validation on input changes
    form.querySelectorAll('input, select').forEach((field) => {
        field.addEventListener('input', validateForm);
        field.addEventListener('change', validateForm);
    });

    // Form submission
    form.addEventListener('submit', submitOpeningForm);
    


    // Initial calculations
    updateAdjustedOpeningBalance();
    validateForm();

    // Prevent form submission on Enter key (except for textarea/button)
    form.addEventListener('keypress', function (event) {
        if (event.key === 'Enter') {
            const target = event.target;
            if (target.tagName !== 'TEXTAREA' && target.tagName !== 'BUTTON') {
                event.preventDefault();
            }
        }
    });
});
