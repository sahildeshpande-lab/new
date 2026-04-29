document.getElementById('queryForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    const dateFrom = document.getElementById('dateFrom').value;
    const dateTo = document.getElementById('dateTo').value;
    const query = document.getElementById('query').value;

    // Validate inputs
    if (!dateFrom || !dateTo) {
        showError('Please select both Date From and Date To');
        return;
    }

    if (!query.trim()) {
        showError('Please enter a query');
        return;
    }

    // Validate date range
    if (new Date(dateFrom) > new Date(dateTo)) {
        showError('Date From must be before Date To');
        return;
    }

    // Prepare the request body
    const requestBody = {
        question: query,
        filters: {
            date_from: dateFrom,
            date_to: dateTo
        },
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

        // Process the data and create chart
        if (data.rows && data.rows.length > 0) {
            createChart(data);
        } else {
            showNoData(data.generated_report || 'No data found for the selected date range and query.');
        }

    } catch (error) {
        console.error('Error:', error);
        showError(`Error: ${error.message}\n\nPlease ensure:\n1. Backend is running on port 8080\n2. Dates are selected and valid\n3. Query is entered`);
    }
});

function showError(message) {
    const chartContainer = document.querySelector('.chart-container');
    chartContainer.innerHTML = `<div class="error-message" style="width: 100%; word-wrap: break-word;">${message}</div>`;
    alert(message);
}

function showNoData(message) {
    const chartContainer = document.querySelector('.chart-container');
    chartContainer.innerHTML = `<div class="no-data">${message}</div>`;
}

function createChart(data) {
    const ctx = document.getElementById('chart').getContext('2d');

    // Clear previous chart if exists
    if (window.myChart) {
        window.myChart.destroy();
    }

    // Handle empty data
    if (!data.rows || data.rows.length === 0) {
        showNoData(data.generated_report || 'No data available for this query.');
        return;
    }

    // Get first two columns for chart
    const labels = data.rows.map(row => {
        const firstCol = data.columns[0];
        return row[firstCol];
    });
    
    const values = data.rows.map(row => {
        const secondCol = data.columns[1];
        return parseFloat(row[secondCol]) || 0;
    });

    window.myChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: data.report_name || 'Report Data',
                data: values,
                backgroundColor: [
                    'rgba(102, 126, 234, 0.8)',
                    'rgba(118, 75, 162, 0.8)',
                    'rgba(159, 122, 234, 0.8)',
                    'rgba(186, 145, 242, 0.8)',
                    'rgba(213, 167, 250, 0.8)',
                ],
                borderColor: [
                    'rgba(102, 126, 234, 1)',
                    'rgba(118, 75, 162, 1)',
                    'rgba(159, 122, 234, 1)',
                    'rgba(186, 145, 242, 1)',
                    'rgba(213, 167, 250, 1)',
                ],
                borderWidth: 2,
                borderRadius: 6,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: true,
                    labels: {
                        font: {
                            size: 14,
                            weight: 'bold'
                        },
                        padding: 15,
                        usePointStyle: true,
                        color: '#2d3748'
                    }
                },
                title: {
                    display: true,
                    text: data.report_name || 'Report Chart',
                    font: {
                        size: 16,
                        weight: 'bold'
                    },
                    padding: 20,
                    color: '#1a202c'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        font: {
                            size: 12
                        },
                        color: '#4a5568'
                    },
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)',
                        drawBorder: false
                    }
                },
                x: {
                    ticks: {
                        font: {
                            size: 12
                        },
                        color: '#4a5568'
                    },
                    grid: {
                        display: false,
                        drawBorder: false
                    }
                }
            }
        }
    });
}