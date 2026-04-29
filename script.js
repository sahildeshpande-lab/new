document.getElementById('queryForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    const query = document.getElementById('query').value;

    if (!query.trim()) {
        showError('Please enter a query');
        return;
    }

    // Prepare the request body (no date filters required)
    const requestBody = {
        question: query,
        filters: {}, // Empty filters object since dates are removed
        format: "json",
        limit: 100
    };

    console.log('Sending request:', requestBody);

    try {
        const response = await fetch('http://localhost:8080/reports/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });

        const data = await response.json();
        console.log('Response data:', data);

        if (!response.ok) {
            const errorDetail = data.detail || response.statusText;
            showError(`Error ${response.status}: ${errorDetail}`);
            return;
        }

        // Check for warnings and display them
        if (data.warnings && data.warnings.length > 0) {
            console.warn('Warnings:', data.warnings);
        }

        // Process the data and create table
        if (data.rows && data.rows.length > 0) {
            window.currentReportData = data;
            document.getElementById('export-controls').style.display = 'flex';
            renderTable(data);
        } else {
            window.currentReportData = null;
            document.getElementById('export-controls').style.display = 'none';
            showNoData(data.generated_report || 'No data found for the selected date range and query.');
        }

    } catch (error) {
        console.error('Error:', error);
        showError(`Error: ${error.message}\n\nPlease ensure Backend is running on port 8080 and Query is entered.`);
    }
});

function showError(message) {
    document.getElementById('export-controls').style.display = 'none';
    const chartContainer = document.querySelector('.chart-container');
    chartContainer.innerHTML = `<div class="error-message" style="width: 100%; word-wrap: break-word;">${message}</div>`;
    alert(message);
}

function showNoData(message) {
    const tableContainer = document.getElementById('table-container');
    const queryContainer = document.getElementById('query-container');
    
    queryContainer.style.display = 'none';
    tableContainer.innerHTML = `<div class="no-data">${message}</div>`;
}

function renderTable(data) {
    const tableContainer = document.getElementById('table-container');
    const queryContainer = document.getElementById('query-container');

    // Display SQL Query Preview
    if (data.sql_preview) {
        queryContainer.textContent = `Generated SQL:\n${data.sql_preview}`;
        queryContainer.style.display = 'block';
    } else {
        queryContainer.style.display = 'none';
    }

    // Handle empty data
    if (!data.rows || data.rows.length === 0) {
        showNoData(data.generated_report || 'No data available for this query.');
        return;
    }

    // Build Table HTML
    let tableHTML = '<table><thead><tr>';
    
    // Add Headers
    data.columns.forEach(col => {
        tableHTML += `<th>${col.replace(/_/g, ' ')}</th>`;
    });
    
    tableHTML += '</tr></thead><tbody>';

    // Add Rows
    data.rows.forEach(row => {
        tableHTML += '<tr>';
        data.columns.forEach(col => {
            const val = row[col];
            tableHTML += `<td>${val !== null && val !== undefined ? val : '-'}</td>`;
        });
        tableHTML += '</tr>';
    });

    tableHTML += '</tbody></table>';
    
    tableContainer.innerHTML = tableHTML;
}

// Export to Excel
document.getElementById('exportExcelBtn').addEventListener('click', async function() {
    const data = window.currentReportData;
    if (!data) return;

    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet('Report Data');

    // Add Headers
    sheet.columns = data.columns.map(col => ({ header: col, key: col, width: 20 }));

    // Add Rows
    data.rows.forEach(row => {
        sheet.addRow(row);
    });

    // Style headers
    sheet.getRow(1).font = { bold: true };
    
    // Generate file
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.report_name || 'report'}.xlsx`;
    a.click();
    window.URL.revokeObjectURL(url);
});

// Export to PDF
document.getElementById('exportPdfBtn').addEventListener('click', function() {
    const data = window.currentReportData;
    if (!data) return;

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF('landscape');

    doc.text(data.report_name || 'Report Data', 14, 15);

    const tableData = data.rows.map(row => data.columns.map(col => row[col]));

    doc.autoTable({
        head: [data.columns],
        body: tableData,
        startY: 20,
        theme: 'grid',
        styles: { fontSize: 8 },
        headStyles: { fillColor: [102, 126, 234] }
    });

    doc.save(`${data.report_name || 'report'}.pdf`);
});