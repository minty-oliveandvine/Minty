document.addEventListener('DOMContentLoaded', function () {
    // DOM Elements
    const openingDrawerInput = document.getElementById('openingDrawer');
    const cashAdditionInput = document.getElementById('additiontocashbalance');
    const adjustedOpeningBalanceInput = document.getElementById('adjustedOpeningBalance');
    const transactionDateInput = document.getElementById('transaction_date');
    const nextTransactionDate = transactionDateInput.dataset.nextTransactionDate; // Assuming the backend sets this data attribute
    const isFirstReport = transactionDateInput.dataset.firstReport === 'true';
    const closingDrawerInput = document.getElementById('closing_balance');
    const cashSalesInput = document.getElementById('shop_sales_cash');
    const shopSalesFields = document.querySelectorAll("#cashSalesContainer input[name^='sales[shop_sales]']");
    const deliverySalesFields = document.querySelectorAll("#deliverySalesContainer input[name^='sales[delivery_sales]']");
    const bankDepositInput = document.getElementById('bank_deposit');
    const coinsInputs = [
        { input: document.getElementById('1coins'), value: 1 },
        { input: document.getElementById('2coins'), value: 2 },
        { input: document.getElementById('5coins'), value: 5 }
    ];
    const noteInputs = [
        { input: document.getElementById('note10'), value: 10 },
        { input: document.getElementById('note20'), value: 20 },
        { input: document.getElementById('note50'), value: 50 },
        { input: document.getElementById('note100'), value: 100 },
        { input: document.getElementById('note500'), value: 500 },
        { input: document.getElementById('note1000'), value: 1000 }
    ];
    const totalActualCashValueInput = document.getElementById('total_actual_cash_value');
    const noExpenseCheckbox = document.getElementById('noE
    const downloadStatementsForm = document.getElementById('downloadStatementsForm');
    const downloadStatementsButton = document.getElementById('downloadStatementsButton');
    const form = document.querySelector('form');

    //Observe DOM Changes and remove inserted flash message
    const observer = new MutationObserver(mutations  => {
        mutations.forEach(mutation => {
            try {xpenseCheckbox');
    const shopExpensesTable = document.querySelector('#shopExpensesContainer tbody');
    const addExpenseButton = document.getElementById('addExpenseButton');
    const grossTotalInput = document.getElementById('grossTotal');
    const totalShopSalesInput = document.getElementById('totalShopSales');
    const totalDeliverySalesInput = document.getElementById('totalDeliverySales');
    const totalSalesInput = document.getElementById('totalSales');
    const submitReportButton = document.getElementById('submitReportButton');
    const flashMessageContainer = document.querySelector('.flash-message');
    const flashContainer = document.querySelector('.flash-container')
    const actualCashError = document.createElement('span');
                setTimeout(() => {
                    mutation.target.childNodes[0].remove()
                }, 3000);
            } catch (error) {
                console.log('Error message element already removed.')
            }
        })
    });
    // Observe flashContainer
    observer.observe(flashContainer, {childList: true, subtree: true})

    form.addEventListener('keypress', function (event) {
        // Check if the key pressed is Enter
        if (event.key === 'Enter') {
            const target = event.target;
            // Allow Enter key only for textarea or button elements
            if (target.tagName !== 'TEXTAREA' && target.tagName !== 'BUTTON') {
                event.preventDefault();
            }
        }
    });

    function saveFormData() {
        const formData = new FormData(document.getElementById('dailyReportForm'));
        console.log("Form Data State (Before Validation/Submission):", [...formData.entries()]);
    }
    
    // Setup Actual Cash Error Display
    actualCashError.id = 'actualCashError';
    actualCashError.className = 'text-danger';
    actualCashError.style.display = 'none';
    totalActualCashValueInput.parentNode.appendChild(actualCashError);

    console.log("Next Transaction Date:", nextTransactionDate);
    console.log("Is First Report:", isFirstReport);

    // Ensure flash messages display on both mobile and desktop
    if (flashMessageContainer) {
        setTimeout(() => flashMessageContainer.style.display = 'none', 5000);
    }

    if (transactionDateInput && nextTransactionDate) {
        transactionDateInput.value = nextTransactionDate; 
        transactionDateInput.readOnly = true; 
    } else {
        console.error('Next transaction date is undefined!');
    }
    

    // Flatpickr for Transaction Date
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
    

    function updateIndividualSales(fieldsContainer, totalInput) {
        let total = 0;
        const fields = fieldsContainer.querySelectorAll("input");
    
        fields.forEach(field => {
            const value = parseFloat(field.value) || 0;
            total += value;
        });
    
        totalInput.value = total.toFixed(2);
    }
    
    shopSalesFields.forEach(field => {
        field.addEventListener('input', () => {
            updateIndividualSales(document.getElementById("cashSalesContainer"), totalShopSalesInput);
            calculateClosingBalance();
        });
    });
    
    deliverySalesFields.forEach(field => {
        field.addEventListener('input', () => {
            updateIndividualSales(document.getElementById("deliverySalesContainer"), totalDeliverySalesInput);
            calculateClosingBalance();
        });
    });
    
    function calculateTotalShopSales() {
        let total = 0;
        shopSalesFields.forEach(field => {
            total += parseFloat(field.value) || 0;
        });
        totalShopSalesInput.value = total.toFixed(2);
        calculateTotalSales();
    }
    
    function calculateTotalDeliverySales() {
        let total = 0;
        deliverySalesFields.forEach(field => {
            total += parseFloat(field.value) || 0;
        });
        totalDeliverySalesInput.value = total.toFixed(2);
        calculateTotalSales();
    }
    

    // Function to calculate adjusted opening balance 

    function updateAdjustedOpeningBalance() {
        const openingBalance = parseFloat(openingDrawerInput.value || 0);
        const cashAddition = parseFloat(cashAdditionInput.value || 0);
        adjustedOpeningBalanceInput.value = (openingBalance + cashAddition).toFixed(2);
    }

    // Attach event listener to `cashAdditionInput`
    cashAdditionInput.addEventListener('input', updateAdjustedOpeningBalance);

    // Ensure openingDrawerInput changes trigger recalculation, if necessary
    openingDrawerInput.addEventListener('input', updateAdjustedOpeningBalance);

    // Function to calculate total sales
    function calculateTotalSales() {
        const totalShopSales = parseFloat(totalShopSalesInput.value) || 0;
        const totalDeliverySales = parseFloat(totalDeliverySalesInput.value) || 0;
        totalSalesInput.value = (totalShopSales + totalDeliverySales).toFixed(2);
        calculateClosingBalance();
    }

    // Function to calculate total shop expenses
    function calculateTotalExpenses() {
        const totalExpenses = Array.from(shopExpensesTable.querySelectorAll('.amount-input')).reduce(
            (total, field) => total + (parseFloat(field.value) || 0),
            0
        );
        grossTotalInput.value = totalExpenses.toFixed(2);
        calculateClosingBalance();
    }

    // Function to calculate closing balance using correct formula: opening + cash_addition + cash_sales - expenses - deposit
    function calculateClosingBalance() {
        const openingDrawer = parseFloat(openingDrawerInput.value) || 0; // Use `.value` to get the input value
        const cashAddition = parseFloat(cashAdditionInput.value) || 0;
        const cashSales = parseFloat(cashSalesInput.value) || 0;
        const totalExpenses = parseFloat(grossTotalInput.value) || 0;
        const bankDeposit = parseFloat(bankDepositInput.value) || 0;
    // Calculate the closing balance using correct formula: opening + cash_addition + cash_sales - expenses - deposit
        const closingBalance = openingDrawer + cashAddition + cashSales - totalExpenses - bankDeposit;

    // Detailed logging for each value
        console.log("Opening Balance:", openingDrawer);
        console.log("Cash Addition:", cashAddition);
        console.log("Cash Sales:", cashSales);
        console.log("Total Expenses:", totalExpenses);
        console.log("Bank Deposit:", bankDeposit);
        console.log(`Calculated Closing Balance: ${closingBalance}`);

    // Update the closing balance input field with the calculated value
        closingDrawerInput.value = closingBalance.toFixed(2);
    }

    // Function to calculate total actual cash from denominations
    function calculateTotalActualCash() {
        let total = 0;
    
        // Sum the values of coin inputs
        coinsInputs.forEach(({ input, value }) => {
            if (input) {
                const inputValue = parseFloat(input.value) || 0;
                console.log(`Coin: ${value} HKD, Count: ${inputValue}`);
                total += inputValue * value;
            } else {
                console.error(`Missing coin input element for value: ${value}`);
            }
        });
    
        // Sum the values of note inputs
        noteInputs.forEach(({ input, value }) => {
            if (input) {
                const inputValue = parseFloat(input.value) || 0;
                console.log(`Note: ${value} HKD, Count: ${inputValue}`);
                total += inputValue * value;
            } else {
                console.error(`Missing note input element for value: ${value}`);
            }
        });
    
        console.log('Total Calculated Cash:', total);
    
        if (totalActualCashValueInput) {
            totalActualCashValueInput.value = total.toFixed(2);
        } else {
            console.error('Total Actual Cash Value Input is missing');
        }
    
        validateActualCash();
    }

    

    // Toggle Expense Section
    function toggleExpenses() {
        const isDisabled = noExpenseCheckbox.checked;
        shopExpensesTable.querySelectorAll('input, select, button').forEach(el => el.disabled = isDisabled);
        addExpenseButton.disabled = isDisabled;
        if (isDisabled) {
            // Set total expenses to 0 and recalculate closing balance
            grossTotalInput.value = '0.00';
        } else {
            // Recalculate total expenses when re-enabling
            calculateTotalExpenses();
        }
    
        // Always recalculate the closing balance when toggling
        calculateClosingBalance();
    }

    // Attach toggle function to checkbox
    noExpenseCheckbox.addEventListener('change', toggleExpenses);

        // Function to handle file previews
        function handleFilePreview(fileInput, previewContainer) {
            previewContainer.innerHTML = ''; // Clear existing previews

            const existingFiles = previewContainer.dataset.existingFiles
            ? JSON.parse(previewContainer.dataset.existingFiles)
            : [];

            console.log('Existing files for preview:', existingFiles);
    
            // Render existing files
            existingFiles.forEach(file => {
                const fileLink = document.createElement('a');
                fileLink.href = file.url;
                fileLink.target = '_blank';
                fileLink.textContent = file.name;
                fileLink.style.display = 'block';
                previewContainer.appendChild(fileLink);
            });
            
            const files = Array.from(fileInput.files); // Get selected files
            files.forEach(file => {
                const fileReader = new FileReader();
        
                fileReader.onload = function (e) {
                    const fileType = file.type;
        
                    if (fileType.startsWith('image/')) {
                        // Image preview
                        const img = document.createElement('img');
                        img.src = e.target.result;
                        img.alt = file.name;
                        img.style.maxWidth = '100%';
                        img.style.height = 'auto';
                        previewContainer.appendChild(img);
                    } else if (fileType === 'application/pdf') {
                        // PDF preview
                        const embed = document.createElement('embed');
                        embed.src = e.target.result;
                        embed.type = 'application/pdf';
                        embed.style.width = '100%';
                        embed.style.height = '300px';
                        previewContainer.appendChild(embed);
                    } else {
                        // Unsupported file type
                        const fallback = document.createElement('p');
                        fallback.textContent = `Cannot preview "${file.name}".`;
                        previewContainer.appendChild(fallback);
        
                        // Add a download link
                        const downloadLink = document.createElement('a');
                        downloadLink.href = e.target.result;
                        downloadLink.download = file.name;
                        downloadLink.textContent = 'Download';
                        downloadLink.style.display = 'block';
                        previewContainer.appendChild(downloadLink);
                    }
                };
        
                // Read the file as a data URL
                fileReader.readAsDataURL(file);
            });
        }

        // Attach event listeners to preview buttons
        document.querySelectorAll('.preview-button').forEach(button => {
            button.addEventListener('click', function () {
                const parentTd = button.closest('td'); // Get the closest <td> element
                const fileInput = parentTd.querySelector('.file-input'); // Find the file input in the same <td>
                const previewContainer = parentTd.querySelector('.file-preview-container'); // Find the preview container in the same <td>

                if (!fileInput || !previewContainer) {
                    console.error('File input or preview container not found for the clicked preview button.');
                    return;
                }

                handleFilePreview(fileInput, previewContainer);
            });
        });


    // Function to add a new expense row
    function createExpenseRow(expense = {}) {
        const rowIndex = shopExpensesTable.querySelectorAll('tr').length;
        const row = document.createElement('tr');
        row.innerHTML = `
            <td data-label="item">
                <select name="shopExpenses[${rowIndex}][item]" class="form-control">
                    <option value="Part Time" ${expense.item === 'Part Time' ? 'selected' : ''}>Part Time</option>
                    <option value="Ingredient" ${expense.item === 'Ingredient' ? 'selected' : ''}>Ingredient</option>
                    <option value="Kitchen Expense" ${expense.item === 'Kitchen Expense' ? 'selected' : ''}>Kitchen Expense</option>
                    <option value="Hall Expense" ${expense.item === 'Hall Expense' ? 'selected' : ''}>Hall Expense</option>
                    <option value="Others" ${expense.item === 'Others' ? 'selected' : ''}>Others</option>
                </select>
            </td>
            <td data-label="Amount (HKD)">
                <input type="number" name="shopExpenses[${rowIndex}][amount]" class="form-control amount-input" value="${expense.amount || 0}" min="0">
            </td>
            <td data-label="Remarks (비고)">
                <input type="text" name="shopExpenses[${rowIndex}][remarks]" class="form-control" value="${expense.remarks || ''}">
            </td>
            <td data-label="Files">
                <input type="file" name="files[${rowIndex}][]" class="form-control-file file-input" multiple>
                <button type="button" class="btn btn-secondary btn-sm mt-2 preview-button">Preview</button>
                <div class="file-preview-container mt-2" style="max-width: 100%; overflow: auto;"></div>
            </td>
            <td data-label="Actions">
                <button type="button" class="btn btn-danger remove-expense">Remove</button>
            </td>
        `;
        shopExpensesTable.appendChild(row);
        attachListenersToExistingRows();

        

   

        // Other event listeners
        row.querySelector('.amount-input').addEventListener('input', calculateTotalExpenses);
        row.querySelector('.remove-expense').addEventListener('click', function () {
            row.remove();
            updateExpenseRowIndexes();
        });

        console.log('Expense Row Added:', row);
    }

    function attachListenersToExistingRows() {
        const rows = document.querySelectorAll('#shopExpensesContainer tbody tr');
        console.log('Attaching preview listeners to rows:', rows.length);
        rows.forEach((row, index) => {
            console.log(`Processing row ${index}`);
            const fileInput = row.querySelector('.file-input');
            const previewButton = row.querySelector('.preview-button');
            const previewContainer = row.querySelector('.file-preview-container');
            
            if (previewButton && fileInput && previewContainer) {
                previewButton.addEventListener('click', () => handleFilePreview(fileInput, previewContainer));
            }
        });
    }

    // Function to remove an expense row
    function removeExpenseRow(event) {
        const button = event.target;
        const row = button.closest('tr'); // Find the closest table row
        if (row) {
            row.remove();
            updateExpenseRowIndexes(); // Update indexes after row removal
        }
    }

    // Event listeners for existing remove buttons
    function attachRemoveExpenseListeners() {
        const removeButtons = document.querySelectorAll('.remove-expense');
        removeButtons.forEach(button => {
            button.addEventListener('click', removeExpenseRow);
        });
    }

    // Attach initial event listeners for "Remove" buttons in existing rows
    attachRemoveExpenseListeners();

    // Update row indexes after a row is removed
    function updateExpenseRowIndexes() {
        const rows = shopExpensesTable.querySelectorAll('tr');
        rows.forEach((row, index) => {
            row.querySelector('select').name = `shopExpenses[${index}][item]`;
            row.querySelector('input[name$="[amount]"]').name = `shopExpenses[${index}][amount]`;
            row.querySelector('input[name$="[remarks]"]').name = `shopExpenses[${index}][remarks]`;
            row.querySelector('input[type="file"]').name = `files[${index}][]`;
        });
        calculateTotalExpenses(); // Recalculate expenses when rows are updated
    }
    


        // Function to handle downloading statements
        async function handleDownloadStatements(event) {
            event.preventDefault(); // Prevent default form submission behavior

            if (!validateExpenseFiles()) {
                showFlashMessages('Each shop expense needs at least one file attached.', 'error');
                return;
            }
    
            const formData = new FormData(downloadStatementsForm);
    
            // Add CSRF token if required
            formData.append('csrf_token', document.querySelector('input[name="csrf_token"]').value);
    
            // Prepare query parameters
            const queryParams = new URLSearchParams();
            formData.forEach((value, key) => {
                if (value) queryParams.append(key, value);
            });
    
            const downloadUrl = `/admin/download_statements?${queryParams.toString()}`;
    
            try {
                // Fetch the file
                const response = await fetch(downloadUrl, {
                    method: 'GET',
                    credentials: 'include', // Include cookies if needed
                });
    
                if (response.ok) {
                    // Get the filename from Content-Disposition header
                    const contentDisposition = response.headers.get('Content-Disposition');
                    const filename = contentDisposition
                        ? contentDisposition.split('filename=')[1].replace(/"/g, '')
                        : 'statements.xlsx';
    
                    // Create a blob and download the file
                    const blob = await response.blob();
                    const downloadLink = document.createElement('a');
                    downloadLink.href = URL.createObjectURL(blob);
                    downloadLink.download = filename;
                    document.body.appendChild(downloadLink);
                    downloadLink.click();
                    document.body.removeChild(downloadLink);
                    console.log('Statements downloaded successfully!');
                } else {
                    const errorText = await response.text();
                    console.error('Error downloading statements:', errorText);
                    showFlashMessages("I couldn't download those statements. Mind checking your filters and trying again?", 'error');
                }
            } catch (error) {
                console.error('Unexpected error during download:', error);
                showFlashMessages("Something went wrong on my end. Mind trying again?", 'error');
            }
        }

    // Attach event listener for downloading statements
    if (downloadStatementsForm && downloadStatementsButton) {
        downloadStatementsButton.addEventListener('click', handleDownloadStatements);
    }
    
    // Event Listeners
    addExpenseButton.addEventListener('click', () => {
        console.log('Add Expense Button Clicked');
        createExpenseRow();
    });
    openingDrawerInput.addEventListener('input', calculateClosingBalance); // Listen to opening balance changes
    cashAdditionInput.addEventListener('input', calculateClosingBalance); // Listen to cash addition changes
    shopSalesFields.forEach(field => field.addEventListener('input', calculateTotalShopSales));
    deliverySalesFields.forEach(field => field.addEventListener('input', calculateTotalDeliverySales));
    cashSalesInput.addEventListener('input', calculateClosingBalance);
    bankDepositInput.addEventListener('input', calculateClosingBalance);
    coinsInputs.forEach(({ input }) => input.addEventListener('input', calculateTotalActualCash));
    noteInputs.forEach(({ input }) => input.addEventListener('input', calculateTotalActualCash));
    shopExpensesTable.addEventListener('input', calculateTotalExpenses);


        function validateTransactionDate() {
        const submittedDate = transactionDateInput.value;
        const expectedDate = transactionDateInput.dataset.nextTransactionDate;
    
        // Skip validation for the first report where expectedDate is undefined
        if (!expectedDate) {
            return true;
        }
    
        if (submittedDate !== expectedDate) {
            showFlashMessages(`Transaction date needs to be ${expectedDate}.`, 'error');
            return false;
        }
        return true;
    }

    // Function to validate files for each expense
    function validateExpenseFiles() {
        if (noExpenseCheckbox.checked) {
            console.log('No expenses selected.');
            return true;
        }
    
        let isValid = true;
    
        shopExpensesTable.querySelectorAll('tr').forEach((row, index) => {
            const amountInput = row.querySelector('.amount-input');
            const fileInput = row.querySelector('input[type="file"]');
    
            const amount = parseFloat(amountInput.value) || 0;
            const filesAttached = fileInput && fileInput.files.length > 0;
    
            if (amount <= 0) {
                amountInput.classList.add('is-invalid');
                isValid = false;
                console.error(`Row ${index}: Invalid expense amount.`);
            } else {
                amountInput.classList.remove('is-invalid');
            }
            
            fileInput.addEventListener('change',function(){
               if(this.files.length > 0){
                this.classList.remove('no-file')
               }else{
                this.classList.add('no-file')
               }
            });

            if (!filesAttached) {
                fileInput.classList.add('is-invalid');
                fileInput.classList.add('no-file')
                isValid = false;
                console.error(`Row ${index}: No file attached.`);
                let message = `Row ${index}: No file attached.`;
                let htmlElement = `<div class="alert text-center col-6 mx-auto position-absolute fixed-top d-flex justify-content-between align-items-center alert-danger flash-message">
                ${message}
            <button type="button" class="close btn btn-danger btn-sm col-1 mt-0" data-dismiss="alert" aria-label="Close">
                <span aria-hidden="true">&times;</span>
            </button>
        </div>`
                flashContainer.insertAdjacentHTML('afterbegin', htmlElement );  

            } else {
                fileInput.classList.remove('is-invalid');
                fileInput.classList.remove('no-file')
            }
        });
    
        return isValid;
    }
    
    // Function to validate actual cash against closing balance
    function validateActualCash() {
        const closingBalance = parseFloat(closingDrawerInput.value) || 0;
        const actualCash = parseFloat(totalActualCashValueInput.value) || 0;
    
        console.log('Validating Cash: Actual = ${actualCash}, Closing Balance = ${closingBalance}');
    
        if (!totalActualCashValueInput.value || actualCash !== closingBalance) {
            totalActualCashValueInput.classList.add("is-invalid");
            actualCashError.textContent = `Actual Cash Value doesn't match Closing Balance / 값이 맞지 않습니다 (${closingBalance.toFixed(2)})`;
            actualCashError.style.display = 'inline';
            return false; // Invalid
        } else {
            totalActualCashValueInput.classList.remove("is-invalid");
            actualCashError.style.display = 'none';
            return true; // Valid
        }
    }
    
    // Function to add fields to FormData, avoiding duplicates
    function addFieldToFormData(formData, key, value) {
        if (!formData.has(key) && value) {
            formData.append(key, value);
        }
    }
    
    // Attach event listener for input validation
    form.querySelectorAll('input, select, textarea').forEach((field) => {
        field.addEventListener('input', validateForm);
    });

    // Attach form submit event
    form.addEventListener('submit', async (event) => {
        event.preventDefault(); // Always prevent default submission

        saveFormData(); // Log current form data before validation and submission

        if (!validateForm()) {
            showFlashMessages("Some fields need a second look before I can save.", 'error');
            return; // Stop submission
        }

        //  await submitForm('/create'); // Proceed to submit if validation passes
    });

    // Initial validation to set the button state
    validateForm();

    // Save form data for debugging
    function saveFormData() {
        const formData = new FormData(form);
        console.log("Form Data State (Before Validation/Submission):", [...formData.entries()]);
    }

    // Validation logic
    function validateForm() {
        let isValid = true;

        // Validate required fields
        const requiredFields = document.querySelectorAll("input[required], select[required], textarea[required]");
        requiredFields.forEach((field) => {
            if (!field.value || field.value.trim() === "") {
                field.classList.add("is-invalid");
                isValid = false;
            } else {
                field.classList.remove("is-invalid");
            }
        });
    
        // Validate transaction date
        if (!validateTransactionDate()) {
            isValid = false;
        }
    
        // Validate expense files
        if (!validateExpenseFiles()) {
            isValid = false;
        }

      // Validate actual cash
        if (!validateActualCash()) {
            isValid = false;
        }

    
        // Debugging logs
        console.log("Validation result:", isValid);
    
        // Enable/Disable submit button
        submitReportButton.disabled = !isValid;
    
        return isValid;
    }
    
   // Form submission

    async function submitForm(actionUrl) {
        console.log("Submit button clicked");

        submitReportButton.disabled = true; // Prevent multiple submissions

        const formData = new FormData(form);

        // Add necessary fields to form data
        addFieldToFormData(formData, 'csrf_token', document.querySelector('input[name="csrf_token"]').value);
        addFieldToFormData(formData, 'opening_balance', openingDrawerInput.value || '0');
        addFieldToFormData(formData, 'cash_addition', cashAdditionInput.value || '0');
        addFieldToFormData(formData, 'transaction_date', transactionDateInput.value || '');
        addFieldToFormData(formData, 'bank_deposit', bankDepositInput.value || '0');
        addFieldToFormData(formData, 'closing_balance', closingDrawerInput.value || '0');
        addFieldToFormData(formData, 'actual_cash_value', totalActualCashValueInput.value || '0');

        // Add shop sales fields
        shopSalesFields.forEach((field) => {
            const match = field.name.match(/\[shop_sales\]\[([a-zA-Z_]+)\]/);
            if (match) {
                const key = `sales[shop_sales][${match[1]}]`;
                addFieldToFormData(formData, key, field.value || '0');
            }
        });

        // Add delivery sales fields
        deliverySalesFields.forEach((field) => {
            const match = field.name.match(/\[delivery_sales\]\[([a-zA-Z_]+)\]/);
            if (match) {
                const key = `sales[delivery_sales][${match[1]}]`;
                addFieldToFormData(formData, key, field.value || '0');
            }
        });

        // Add expense rows
        shopExpensesTable.querySelectorAll('tr').forEach((row, index) => {
            const item = row.querySelector('select').value || '';
            const amount = row.querySelector('.amount-input').value || '0';
            const remarks = row.querySelector('input[type="text"]').value || '';

            formData.append(`shopExpenses[${index}][item]`, item);
            formData.append(`shopExpenses[${index}][amount]`, amount);
            formData.append(`shopExpenses[${index}][remarks]`, remarks);

            // Clear previously added files to avoid duplicates
            formData.delete(`files[${index}][]`); 


            const fileInput = row.querySelector('input[type="file"]');
            Array.from(fileInput.files).forEach((file) => {
                console.log(`Appending file: ${file.name} for row index: ${index}`);
                formData.append(`files[${index}][]`, file, file.name);
            });
        });

        console.log("FormData prepared:", [...formData.entries()]);

        try {
            const response = await fetch(actionUrl, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'include', // Include credentials if required by server
            });

            console.log("Response received with status:", response.status);

            if (response.ok) {
                const data = await response.json();
                if (data.status === 'success') {
                    showFlashMessages(data.message || 'Report submitted.', 'success');
                    if (data.redirect_url) {
                        window.location.href = data.redirect_url;
                    }
                } else {
                    showFlashMessages(data.message || "I couldn't save that. Mind trying again?", 'error');
                }
            } else {
                const errorText = await response.text();
                console.error("Server error response:", errorText);
                console.error("Submission failed. Please try again.");
            }
        } catch (error) {
            console.log(error)
            console.error("Unexpected error during form submission:", error);
            showFlashMessages("Something went wrong on my end. Mind trying again?", 'error');
        } finally {
            submitReportButton.disabled = false; // Re-enable button after submission attempt
        }
    }
   

    

    // Initial Calculations
    updateAdjustedOpeningBalance();
    calculateTotalSales();
    calculateTotalExpenses();
    calculateClosingBalance();
    toggleExpenses();
    attachListenersToExistingRows();
});
