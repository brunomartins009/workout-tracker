// Exercise history modal on the workout detail page.
//
// Each "Histórico" button carries the URL of GET /exercises/<id>/history.
// The JSON already contains the table rows (most recent first) and the chart
// series (oldest first), so this file only opens the dialog and renders them.
//
// Content is built with textContent, never innerHTML, because workout names
// are typed by the user.
(function () {
  "use strict";

  const dialog = document.getElementById("exercise-history-dialog");
  if (!dialog) {
    return;
  }

  const exerciseNameElement = dialog.querySelector("[data-history-exercise-name]");
  const body = dialog.querySelector("[data-history-body]");
  let chart = null;
  // Ignores a slow response that arrives after the user opened another
  // exercise or closed the modal.
  let currentRequest = 0;

  document.querySelectorAll("[data-history-url]").forEach(function (button) {
    button.addEventListener("click", function () {
      openHistory(button.dataset.historyUrl, button.dataset.exerciseName);
    });
  });

  dialog.querySelector("[data-history-close]").addEventListener("click", function () {
    dialog.close();
  });

  // The dialog element has no padding and its content fills it, so a click
  // whose target is the dialog itself happened on the backdrop.
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) {
      dialog.close();
    }
  });

  // Fired for every way of closing: X button, backdrop click and Escape.
  dialog.addEventListener("close", function () {
    currentRequest += 1;
    destroyChart();
    body.replaceChildren();
    document.body.classList.remove("modal-open");
  });

  function openHistory(url, exerciseName) {
    const request = ++currentRequest;
    destroyChart();
    exerciseNameElement.textContent = exerciseName;
    showMessage("Carregando histórico...");
    document.body.classList.add("modal-open");
    dialog.showModal();

    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        if (request === currentRequest) {
          renderHistory(data);
        }
      })
      .catch(function () {
        if (request === currentRequest) {
          showMessage("Não foi possível carregar o histórico. Tente novamente.");
        }
      });
  }

  function renderHistory(data) {
    exerciseNameElement.textContent = data.exercise.name;

    if (data.history.length === 0) {
      showMessage("Nenhum histórico disponível para este exercício.");
      return;
    }

    body.replaceChildren(buildTable(data.history), buildChartContainer());
    renderChart(data.chart);
  }

  function showMessage(text) {
    const message = document.createElement("p");
    message.className = "muted modal-message";
    message.textContent = text;
    body.replaceChildren(message);
  }

  function buildTable(history) {
    const wrapper = document.createElement("div");
    wrapper.className = "panel table-wrapper";

    const table = document.createElement("table");
    table.className = "data-table history-table";

    const caption = document.createElement("caption");
    caption.className = "visually-hidden";
    caption.textContent = "Histórico do exercício, do treino mais recente para o mais antigo";
    table.appendChild(caption);

    const headerRow = document.createElement("tr");
    [
      ["Data", ""],
      ["Treino", ""],
      ["Séries", "numeric"],
      ["Repetições", "numeric"],
      ["Maior peso", "numeric"],
    ].forEach(function (column) {
      const header = document.createElement("th");
      header.scope = "col";
      header.className = column[1];
      header.textContent = column[0];
      headerRow.appendChild(header);
    });
    table.createTHead().appendChild(headerRow);

    const tableBody = table.createTBody();
    history.forEach(function (occurrence) {
      const row = tableBody.insertRow();
      addCell(row, formatDate(occurrence.date), "");
      addCell(row, occurrence.workout_name, "");
      addCell(row, String(occurrence.sets), "numeric");
      addCell(row, String(occurrence.repetitions), "numeric");
      addCell(row, formatWeight(occurrence.max_weight_kg), "numeric");
    });

    wrapper.appendChild(table);
    return wrapper;
  }

  function addCell(row, text, className) {
    const cell = row.insertCell();
    cell.className = className;
    cell.textContent = text;
  }

  function buildChartContainer() {
    const container = document.createElement("div");
    container.className = "history-chart";
    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute(
      "aria-label",
      "Gráfico da evolução do total de repetições e do maior peso por treino; os mesmos valores estão na tabela acima."
    );
    container.appendChild(canvas);
    return container;
  }

  function renderChart(chartData) {
    // The table is still useful if the chart library failed to load.
    if (typeof window.Chart === "undefined") {
      return;
    }

    const styles = getComputedStyle(document.documentElement);
    const repetitionsColor = styles.getPropertyValue("--color-accent").trim();
    const weightColor = styles.getPropertyValue("--color-chart-weight").trim();
    const canvas = body.querySelector(".history-chart canvas");

    chart = new window.Chart(canvas, {
      type: "line",
      data: {
        labels: chartData.labels.map(formatDate),
        datasets: [
          {
            label: "Total de repetições",
            data: chartData.repetitions,
            yAxisID: "repetitions",
            borderColor: repetitionsColor,
            backgroundColor: repetitionsColor,
            tension: 0.2,
            spanGaps: false,
          },
          {
            label: "Maior peso (kg)",
            data: chartData.max_weight_kg,
            yAxisID: "weight",
            borderColor: weightColor,
            backgroundColor: weightColor,
            tension: 0.2,
            spanGaps: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              // Several workouts can share a date, so the title names the workout too.
              title: function (items) {
                const index = items[0].dataIndex;
                return chartData.workout_names[index] + " — " + formatDate(chartData.labels[index]);
              },
            },
          },
        },
        scales: {
          repetitions: {
            type: "linear",
            position: "left",
            beginAtZero: true,
            title: { display: true, text: "Repetições" },
            ticks: { precision: 0 },
          },
          weight: {
            type: "linear",
            position: "right",
            beginAtZero: true,
            title: { display: true, text: "Peso (kg)" },
            grid: { drawOnChartArea: false },
          },
        },
      },
    });
  }

  function destroyChart() {
    if (chart) {
      chart.destroy();
      chart = null;
    }
  }

  // "2026-10-07" -> "07/10/2026", matching the dates shown elsewhere in the app.
  function formatDate(isoDate) {
    const parts = isoDate.split("-");
    return parts[2] + "/" + parts[1] + "/" + parts[0];
  }

  // Same format as the sets table: two decimals followed by "kg".
  function formatWeight(weight) {
    return weight === null ? "—" : weight.toFixed(2) + " kg";
  }
})();
