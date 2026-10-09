// Behaviour of the workout pages:
//
// 1. Calendar (workouts/list.html): a day with several workouts opens a dialog
//    with their cards. The cards are rendered by Jinja inside a <template>, so
//    workout names arrive already escaped and are only copied here.
// 2. Workout page (workouts/detail.html): exercises expand and collapse.
// 3. Workout page: sets are added, edited and deleted with fetch(). The set
//    routes answer with the re-rendered sets area of that exercise (from the
//    same Jinja template used by the page), which replaces the old one.
(function () {
  "use strict";

  setUpDayWorkoutsDialog();
  setUpExerciseToggles();
  setUpSetForms();

  // ---------------------------------------------------------------------------
  // 1. Calendar: workouts of a day
  // ---------------------------------------------------------------------------

  function setUpDayWorkoutsDialog() {
    const dialog = document.getElementById("day-workouts-dialog");
    if (!dialog) {
      return;
    }
    const label = dialog.querySelector("[data-day-workouts-label]");
    const list = dialog.querySelector("[data-day-workouts-list]");

    document.querySelectorAll("[data-day-workouts]").forEach(function (button) {
      button.addEventListener("click", function () {
        const template = document.getElementById(button.dataset.dayWorkouts);
        label.textContent = button.dataset.dayLabel;
        list.replaceChildren(template.content.cloneNode(true));
        document.body.classList.add("modal-open");
        dialog.showModal();
      });
    });

    closeOnCloseButtonAndBackdrop(dialog, dialog.querySelector("[data-day-workouts-close]"));

    // Close before following a card link, so the dialog is not open when the
    // user comes back to this page.
    list.addEventListener("click", function (event) {
      if (event.target.closest("a")) {
        dialog.close();
      }
    });

    dialog.addEventListener("close", function () {
      list.replaceChildren();
      document.body.classList.remove("modal-open");
    });
  }

  // Same closing rules as the exercise modal: X button, Escape (native
  // <dialog> behaviour) and a click on the backdrop. The dialog has no padding
  // and its content fills it, so a click whose target is the dialog itself
  // happened on the backdrop.
  function closeOnCloseButtonAndBackdrop(dialog, closeButton) {
    closeButton.addEventListener("click", function () {
      dialog.close();
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) {
        dialog.close();
      }
    });
  }

  // ---------------------------------------------------------------------------
  // 2. Workout page: collapsible exercises
  // ---------------------------------------------------------------------------

  function setUpExerciseToggles() {
    const toggles = document.querySelectorAll("[data-exercise-toggle]");
    toggles.forEach(function (toggle) {
      toggle.addEventListener("click", function () {
        setExpanded(toggle, toggle.getAttribute("aria-expanded") !== "true");
      });
    });

    // After adding an exercise the server redirects to #exercise-<id>; open it.
    if (window.location.hash) {
      const card = document.getElementById(window.location.hash.slice(1));
      const toggle = card && card.querySelector("[data-exercise-toggle]");
      if (toggle) {
        setExpanded(toggle, true);
        card.scrollIntoView({ block: "start" });
      }
    }
  }

  function setExpanded(toggle, expanded) {
    toggle.setAttribute("aria-expanded", String(expanded));
    document.getElementById(toggle.getAttribute("aria-controls")).hidden = !expanded;
  }

  // ---------------------------------------------------------------------------
  // 3. Workout page: sets without reloading
  // ---------------------------------------------------------------------------

  function setUpSetForms() {
    const cards = document.querySelectorAll(".exercise-card");
    if (cards.length === 0) {
      return;
    }
    // Event delegation: the sets area is replaced after each change, so the
    // listeners live on the card, which is never replaced.
    cards.forEach(function (card) {
      card.addEventListener("submit", function (event) {
        const form = event.target.closest("[data-set-form]");
        if (form) {
          event.preventDefault();
          submitSetForm(card, form);
        }
      });

      card.addEventListener("click", function (event) {
        const editLink = event.target.closest("[data-edit-set]");
        if (editLink) {
          event.preventDefault();
          showEditRow(editLink);
          return;
        }
        const cancelButton = event.target.closest("[data-cancel-edit]");
        if (cancelButton) {
          hideEditRow(cancelButton.closest(".set-edit-row"));
        }
      });
    });
  }

  function showEditRow(editLink) {
    const editRow = document.getElementById(editLink.dataset.editSet);
    editRow.previousElementSibling.hidden = true;
    editRow.hidden = false;
    editRow.querySelector("input").focus();
  }

  function hideEditRow(editRow) {
    editRow.querySelector("form").reset();
    editRow.hidden = true;
    editRow.previousElementSibling.hidden = false;
    editRow.previousElementSibling.querySelector("[data-edit-set]").focus();
  }

  function submitSetForm(card, form) {
    // Only one set operation per exercise at a time.
    if (card.dataset.busy === "true") {
      return;
    }
    setBusy(card, true);

    const isAddForm = form.classList.contains("add-set-form");
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return null;
          })
          .then(function (data) {
            return { ok: response.ok, data: data };
          });
      })
      .then(function (result) {
        // The page only changes after a successful answer from the server.
        if (result.ok && result.data && result.data.sets_html) {
          replaceSets(card, result.data.sets_html);
          updateTotalSets(result.data.total_sets);
          showFeedback(card, result.data.message, "success");
          // The clicked control was replaced, so put the focus somewhere useful:
          // the next set's repetitions after adding, the exercise otherwise.
          if (isAddForm) {
            card.querySelector(".add-set-form input").focus();
          } else {
            card.querySelector("[data-exercise-toggle]").focus();
          }
        } else {
          const message = result.data && result.data.error;
          showFeedback(card, message || "Não foi possível salvar a série. Tente novamente.", "error");
        }
      })
      .catch(function () {
        showFeedback(card, "Não foi possível conectar ao servidor. Tente novamente.", "error");
      })
      .finally(function () {
        setBusy(card, false);
      });
  }

  function setBusy(card, busy) {
    card.dataset.busy = String(busy);
    card.setAttribute("aria-busy", String(busy));
    card.querySelectorAll("[data-sets] button").forEach(function (button) {
      button.disabled = busy;
    });
  }

  // The HTML comes from the app's own Jinja template (autoescaped), never from
  // user input. DOMParser builds the nodes without running scripts.
  function replaceSets(card, html) {
    const parsed = new DOMParser().parseFromString(html, "text/html");
    const newSets = parsed.querySelector("[data-sets]");
    card.querySelector("[data-sets]").replaceWith(newSets);
  }

  function updateTotalSets(totalSets) {
    const totalSetsElement = document.querySelector(".stats .set-count");
    if (totalSetsElement && typeof totalSets === "number") {
      totalSetsElement.textContent = String(totalSets);
    }
  }

  function showFeedback(card, message, kind) {
    const feedback = card.querySelector("[data-set-feedback]");
    window.clearTimeout(Number(feedback.dataset.timeout));
    feedback.textContent = message;
    feedback.className = "set-feedback set-feedback-" + kind;
    // Success messages fade away on their own; errors stay until the next action.
    if (kind === "success") {
      feedback.dataset.timeout = String(
        window.setTimeout(function () {
          feedback.textContent = "";
        }, 4000)
      );
    }
  }
})();
