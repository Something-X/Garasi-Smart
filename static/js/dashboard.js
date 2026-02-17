const ctx = document.getElementById('usageChart');

if(ctx){
new Chart(ctx, {
    type: 'bar',
    data: {
        labels: ['Sen', 'Sel', 'Rab', 'Kam', 'Jum'],
        datasets: [{
            label: 'Dibuka',
            data: [5, 8, 4, 6, 7],
            backgroundColor: '#f1c40f'
        },
        {
            label: 'Ditutup',
            data: [5, 8, 4, 6, 7],
            backgroundColor: '#3498db'
        }]
    }
});
}
