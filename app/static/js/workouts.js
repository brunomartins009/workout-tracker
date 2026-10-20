// Behaviour of the workout pages:
//
// 1. Calendar (workouts/list.html): a day with several workouts opens a dialog
//    with their cards. The cards are rendered by Jinja inside a <template>, so
//    workout names arrive already escaped and are only copied here.
// 2. Workout page (workouts/detail.html): exercises expand and collapse.
// 3. Workout page: sets are added, edited and deleted with fetch(). The set
//    routes answer with the re-rendered sets area of that exercise (from the
//    same Jinja template used by the page), which replaces the old one.
// 4. Workout page: exercises are added, removed and reordered (drag and drop,
//    sortable_list.js) with fetch(); the routes answer with the re-rendered
//    exercise list, which replaces the old one. Listeners are delegated to the
//    document (or attached again) so they keep working on the new HTML.
// 5. Workout and template pages: completing a workout, deleting a workout or
//    a template, and removing an exercise from a workout ask for confirmation.
// 6. Template overview: "Iniciar treino" is sent only once, so a double
//    click does not start two sessions.
// 7. Workout page: the name and the date of a session in progress are changed
//    in place (click, edit, save with fetch()).
// 8. Workout page: leaving with typed values not saved yet asks the browser
//    to confirm.
(function () {
  "use strict";

  // True while an exercise change is waiting for the server.
  let exercisesBusy = false;
  const BUSY_MESSAGE = "Aguarde a operação anterior terminar e tente novamente.";

  setUpDayWorkoutsDialog();
  setUpExerciseToggles();
  setUpSetForms();
  setUpExerciseForms();
  setUpExerciseSorting();
  setUpConfirmDialogs();
  setUpSubmitOnceForms();
  setUpSessionDetails();
  // Last: its submit listener must run after the ones that send with fetch().
  setUpUnsavedValuesWarning();

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
    // Delegated to the document: the exercise list is replaced after an
    // exercise is added, removed or moved, and new toggles must work too.
    document.addEventListener("click", function (event) {
      const toggle = event.target.closest("[data-exercise-toggle]");
      if (toggle) {
        setExpanded(toggle, toggle.getAttribute("aria-expanded") !== "true");
      }
    });

    // Without JavaScript, adding an exercise redirects to #exercise-<id>; open it.
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
    // Event delegation on the document: the sets area is replaced after each
    // set change, and the whole exercise list after each exercise change.
    document.addEventListener("submit", function (event) {
      const form = event.target.closest("[data-set-form]");
      if (form) {
        event.preventDefault();
        submitSetForm(form.closest(".exercise-card"), form);
      }
    });

    document.addEventListener("click", function (event) {
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
    // Only one set operation per exercise at a time, and none while the
    // exercise list itself is being changed (it would replace this card).
    if (card.dataset.busy === "true") {
      return;
    }
    if (exercisesBusy) {
      showFeedback(card, BUSY_MESSAGE, "error");
      return;
    }
    setBusy(card, true);

    const isAddForm = form.classList.contains("add-set-form");
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json" },
    })
      .then(readJsonResponse)
      .then(function (result) {
        // The page only changes after a successful answer from the server.
        if (result.ok && result.data && result.data.sets_html) {
          replaceSets(card, result.data.sets_html);
          updateTotalSets(result.data.total_sets);
          replaceProgress(card, result.data.progress_html);
          showFeedback(card, result.data.message, "success");
          // The clicked control was replaced, so put the focus somewhere useful:
          // the next set's repetitions after adding, the exercise otherwise.
          if (isAddForm) {
            card.querySelector(".add-set-form input").focus();
          } else {
            card.querySelector("[data-exercise-toggle]").focus();
          }
        } else {
          showFeedback(
            card,
            errorMessage(
              result,
              "Não foi possível salvar a série. Tente novamente.",
              "Esta série ou este exercício não existe mais neste treino. Recarregue a página."
            ),
            "error"
          );
        }
      })
      .catch(function () {
        showFeedback(card, "Não foi possível conectar ao servidor. Tente novamente.", "error");
      })
      .finally(function () {
        setBusy(card, false);
      });
  }

  // Reads the JSON of a fetch() answer; errors without JSON give data = null.
  function readJsonResponse(response) {
    return response
      .json()
      .catch(function () {
        return null;
      })
      .then(function (data) {
        return { ok: response.ok, status: response.status, data: data };
      });
  }

  // The message for a refused request: the server's own error when it sent
  // one. A 404 comes as an HTML page, without JSON: what the request refers to
  // no longer exists (for example, deleted in another tab).
  function errorMessage(result, fallback, notFoundMessage) {
    if (result.data && result.data.error) {
      return result.data.error;
    }
    return result.status === 404 ? notFoundMessage : fallback;
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

  // Recorded sets against the target, in the card header (rendered by the
  // server from the same template as the page).
  function replaceProgress(card, html) {
    const current = card.querySelector("[data-progress]");
    if (!current || !html) {
      return;
    }
    const parsed = new DOMParser().parseFromString(html, "text/html");
    current.replaceWith(parsed.querySelector("[data-progress]"));
  }

  function updateTotalSets(totalSets) {
    const totalSetsElement = document.querySelector(".stats .set-count");
    if (totalSetsElement && typeof totalSets === "number") {
      totalSetsElement.textContent = String(totalSets);
    }
  }

  function showFeedback(card, message, kind) {
    showMessage(card.querySelector("[data-set-feedback]"), message, kind);
  }

  function showMessage(feedback, message, kind) {
    window.clearTimeout(Number(feedback.dataset.timeout));
    feedback.textContent = message;
    feedback.classList.remove("set-feedback-success", "set-feedback-error");
    feedback.classList.add("set-feedback-" + kind);
    // Success messages fade away on their own; errors stay until the next action.
    if (kind === "success") {
      feedback.dataset.timeout = String(
        window.setTimeout(function () {
          feedback.textContent = "";
        }, 4000)
      );
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Workout page: add, remove and move exercises without reloading
  // ---------------------------------------------------------------------------

  // The exercise routes answer with the re-rendered exercise list (from the
  // same Jinja template used by the page), which replaces the old one: an
  // exercise change renumbers positions, so the whole list is the unit that
  // changes. The server stays the
  // source of truth (duplicates, completed sessions, missing exercises).
  function setUpExerciseForms() {
    document.addEventListener("submit", function (event) {
      const form = event.target.closest("[data-exercise-form]");
      if (form) {
        event.preventDefault();
        submitExerciseForm(form);
      }
    });
  }

  function submitExerciseForm(form) {
    const action = form.dataset.exerciseForm;
    // Messages appear next to the control that was used.
    const feedback = document.querySelector(
      action === "add" ? "[data-add-exercise-feedback]" : "[data-exercise-feedback]"
    );
    // One exercise change at a time, and none while a set is being saved
    // (its card would be replaced before the answer arrives). The user is told,
    // since a confirmed removal would otherwise seem to do nothing.
    if (exercisesBusy || document.querySelector('.exercise-card[data-busy="true"]')) {
      showMessage(feedback, BUSY_MESSAGE, "error");
      return;
    }

    const card = form.closest(".exercise-card");
    const cards = Array.prototype.slice.call(document.querySelectorAll("[data-exercise-list] .exercise-card"));
    const position = cards.indexOf(card);
    setExercisesBusy(true);

    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json" },
    })
      .then(readJsonResponse)
      .then(function (result) {
        // The page only changes after a successful answer from the server.
        if (result.ok && result.data && result.data.exercises_html) {
          replaceExerciseList(result.data.exercises_html, result.data.added_workout_exercise_id);
          updateExerciseCount(result.data.exercise_count);
          updateTotalSets(result.data.total_sets);
          showMessage(feedback, result.data.message, "success");
          focusAfterExerciseChange(action, card ? card.id : null, position);
        } else {
          showMessage(
            feedback,
            errorMessage(
              result,
              "Não foi possível alterar os exercícios. Tente novamente.",
              "Este treino ou este exercício não existe mais. Recarregue a página."
            ),
            "error"
          );
        }
      })
      .catch(function () {
        showMessage(feedback, "Não foi possível conectar ao servidor. Tente novamente.", "error");
      })
      .finally(function () {
        setExercisesBusy(false);
        if (action === "add") {
          form.querySelector("select").focus({ preventScroll: true });
        }
      });
  }

  function setExercisesBusy(busy) {
    exercisesBusy = busy;
    document.querySelectorAll("[data-exercise-form] button").forEach(function (button) {
      button.disabled = busy;
    });
  }

  function replaceExerciseList(html, addedWorkoutExerciseId) {
    const list = document.querySelector("[data-exercise-list]");
    // Cards keep their id (exercise-<workout exercise id>) across changes, so
    // the exercises that were open are opened again after the replacement.
    const expandedCardIds = Array.prototype.map.call(
      list.querySelectorAll('[data-exercise-toggle][aria-expanded="true"]'),
      function (toggle) {
        return toggle.closest(".exercise-card").id;
      }
    );
    // A newly added exercise opens, ready for its first set.
    if (addedWorkoutExerciseId) {
      expandedCardIds.push("exercise-" + addedWorkoutExerciseId);
    }
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;

    const parsed = new DOMParser().parseFromString(html, "text/html");
    list.replaceWith(parsed.querySelector("[data-exercise-list]"));

    expandedCardIds.forEach(function (cardId) {
      const card = document.getElementById(cardId);
      const toggle = card && card.querySelector("[data-exercise-toggle]");
      if (toggle) {
        setExpanded(toggle, true);
      }
    });
    window.scrollTo(scrollX, scrollY);
    // The new list needs its drag-and-drop again.
    setUpExerciseSorting();
  }

  function updateExerciseCount(exerciseCount) {
    const exerciseCountElement = document.querySelector(".stats .exercise-count");
    if (exerciseCountElement && typeof exerciseCount === "number") {
      exerciseCountElement.textContent = String(exerciseCount);
    }
  }

  // The clicked control was replaced. After a removal, focus moves without
  // scrolling to the exercise that took the removed one's place.
  function focusAfterExerciseChange(action, cardId, position) {
    let target = null;
    if (action === "remove") {
      const cards = document.querySelectorAll("[data-exercise-list] .exercise-card");
      const card = cards[Math.min(position, cards.length - 1)];
      target = card
        ? card.querySelector("[data-exercise-toggle]")
        : document.querySelector('[data-exercise-form="add"] select');
    }
    if (target) {
      target.focus({ preventScroll: true });
    }
  }

  // Drag and drop (or the arrow keys on the handle) reorders the exercises of
  // a session in progress. The new order shows at once and is sent whole to
  // the server, which answers with the re-rendered list. If the server refuses
  // it, or another change is still running, the saved order (the positions
  // rendered by the server) is put back.
  function setUpExerciseSorting() {
    const list = document.querySelector("[data-sortable-exercises]");
    if (!list || !window.SortableList) {
      return;
    }
    window.SortableList.attach(list, {
      handleSelector: "[data-drag-handle]",
      onMove: function (from, to) {
        reorderExercises(list, from, to);
      },
    });
  }

  function reorderExercises(list, from, to) {
    const feedback = document.querySelector("[data-exercise-feedback]");
    const savedOrder = savedExerciseOrder(list);
    const newOrder = savedOrder.slice();
    const moved = newOrder.splice(from, 1)[0];
    newOrder.splice(to, 0, moved);

    if (exercisesBusy || document.querySelector('.exercise-card[data-busy="true"]')) {
      showExerciseOrder(list, savedOrder);
      showMessage(feedback, BUSY_MESSAGE, "error");
      return;
    }

    // A keyboard move has not moved anything yet; a drag already has.
    showExerciseOrder(list, newOrder);
    setExercisesBusy(true);
    list.setAttribute("aria-busy", "true");

    const data = new FormData();
    newOrder.forEach(function (card) {
      data.append("workout_exercise_ids", card.dataset.workoutExerciseId);
    });

    fetch(list.dataset.reorderUrl, {
      method: "POST",
      body: data,
      headers: { Accept: "application/json" },
    })
      .then(readJsonResponse)
      .then(function (result) {
        if (result.ok && result.data && result.data.exercises_html) {
          replaceExerciseList(result.data.exercises_html, null);
          updateExerciseCount(result.data.exercise_count);
          updateTotalSets(result.data.total_sets);
          showMessage(feedback, result.data.message, "success");
          // Keep the focus on the moved exercise's handle (arrow keys again).
          const card = document.getElementById(moved.id);
          const handle = card && card.querySelector("[data-drag-handle]");
          if (handle) {
            handle.focus({ preventScroll: true });
          }
        } else {
          showExerciseOrder(list, savedOrder);
          showMessage(
            feedback,
            errorMessage(
              result,
              "Não foi possível salvar a nova ordem. Tente novamente.",
              "Este treino não existe mais. Recarregue a página."
            ),
            "error"
          );
        }
      })
      .catch(function () {
        showExerciseOrder(list, savedOrder);
        showMessage(feedback, "Não foi possível conectar ao servidor. Tente novamente.", "error");
      })
      .finally(function () {
        list.removeAttribute("aria-busy");
        setExercisesBusy(false);
      });
  }

  // The cards in the order saved on the server (their rendered positions).
  function savedExerciseOrder(list) {
    return Array.prototype.slice.call(list.querySelectorAll(":scope > .exercise-card")).sort(function (a, b) {
      return Number(a.dataset.position) - Number(b.dataset.position);
    });
  }

  function showExerciseOrder(list, cards) {
    cards.forEach(function (card) {
      list.appendChild(card);
    });
  }

  // ---------------------------------------------------------------------------
  // 5. Confirmation before completing a workout or deleting/removing something
  // ---------------------------------------------------------------------------

  // A form with data-confirm-dialog="<dialog id>" opens that dialog instead of
  // submitting. Several forms may share one dialog (one per template card or
  // per exercise would repeat the same markup); data-confirm-name is then
  // shown in the dialog's [data-confirm-name].
  //
  // The listener is delegated to the document, so forms added later (the
  // exercise list is replaced after each change) ask for confirmation too. It
  // runs in the capture phase, before the fetch() handlers of section 4, and
  // stops the submission until the user confirms. "Confirmar" then submits the
  // same form again with requestSubmit(), marked as confirmed: a fetch form is
  // sent by its handler as usual, any other form is submitted by the browser.
  // The server still validates everything.
  function setUpConfirmDialogs() {
    const pendingForms = new Map();

    document.addEventListener(
      "submit",
      function (event) {
        const form = event.target.closest("form[data-confirm-dialog]");
        if (!form) {
          return;
        }
        if (form.dataset.confirmed === "true") {
          delete form.dataset.confirmed;
          return;
        }
        const dialog = document.getElementById(form.dataset.confirmDialog);
        if (!dialog) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        pendingForms.set(dialog, form);
        const nameElement = dialog.querySelector("[data-confirm-name]");
        if (nameElement) {
          nameElement.textContent = form.dataset.confirmName || "";
        }
        document.body.classList.add("modal-open");
        dialog.showModal();
      },
      true
    );

    document.querySelectorAll("dialog").forEach(function (dialog) {
      const acceptButton = dialog.querySelector("[data-confirm-accept]");
      if (!acceptButton) {
        return;
      }

      // X, Cancelar and the backdrop close it (Escape is native). Closing
      // never submits anything.
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog || event.target.closest("[data-confirm-close]")) {
          dialog.close();
        }
      });

      acceptButton.addEventListener("click", function () {
        const form = pendingForms.get(dialog);
        pendingForms.delete(dialog);
        // The form may have left the page in the meantime (list replaced).
        if (!form || !form.isConnected) {
          dialog.close();
          return;
        }
        if (form.hasAttribute("data-exercise-form")) {
          // Sent with fetch(): the page stays, so the dialog closes now.
          dialog.close();
        } else {
          // The browser loads the next page; the disabled button prevents a
          // second submission meanwhile.
          acceptButton.disabled = true;
        }
        form.dataset.confirmed = "true";
        form.requestSubmit();
      });

      dialog.addEventListener("close", function () {
        pendingForms.delete(dialog);
        document.body.classList.remove("modal-open");
      });

      // Coming back with the browser's Back button may restore this page as it
      // was left: dialog open and button disabled.
      window.addEventListener("pageshow", function (event) {
        if (event.persisted) {
          acceptButton.disabled = false;
          dialog.close();
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // 6. Forms sent only once
  // ---------------------------------------------------------------------------

  // A form with data-submit-once is submitted by the browser once; further
  // submissions while the next page loads are ignored, so a double click on
  // "Iniciar" does not start two sessions.
  function setUpSubmitOnceForms() {
    document.addEventListener("submit", function (event) {
      const form = event.target.closest("form[data-submit-once]");
      if (!form || event.defaultPrevented) {
        return;
      }
      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = "true";
      form.querySelectorAll('button[type="submit"]').forEach(function (button) {
        button.disabled = true;
      });
    });

    // Coming back with the browser's Back button may restore the page with
    // the form still marked as submitted.
    window.addEventListener("pageshow", function (event) {
      if (event.persisted) {
        document.querySelectorAll("form[data-submit-once]").forEach(function (form) {
          delete form.dataset.submitting;
          form.querySelectorAll('button[type="submit"]').forEach(function (button) {
            button.disabled = false;
          });
        });
      }
    });
  }

  // ---------------------------------------------------------------------------
  // 7. Session name and date, changed in place
  // ---------------------------------------------------------------------------

  // Each value in the header ([data-inline-edit-open]) opens its small form
  // ([data-inline-edit]), which sends only that field to POST /workouts/<id>/edit
  // and asks for JSON. The server validates and answers 400 (invalid value)
  // or 409 (session completed meanwhile); the form then stays open with what
  // was typed. Escape or "Cancelar" closes it without saving.
  function setUpSessionDetails() {
    const feedback = document.querySelector("[data-session-feedback]");
    if (!feedback) {
      return;
    }

    document.querySelectorAll("[data-inline-edit-open]").forEach(function (trigger) {
      const form = document.getElementById(trigger.dataset.inlineEditOpen);
      trigger.addEventListener("click", function () {
        trigger.hidden = true;
        form.hidden = false;
        form.querySelector("input").focus();
      });

      form.querySelector("[data-inline-edit-cancel]").addEventListener("click", function () {
        closeInlineEdit(form, trigger);
      });
      form.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          event.preventDefault();
          closeInlineEdit(form, trigger);
        }
      });
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        submitInlineEdit(form, trigger, feedback);
      });
    });
  }

  // Closing without saving puts back the saved value.
  function closeInlineEdit(form, trigger) {
    const input = form.querySelector("input");
    input.value = input.defaultValue;
    form.hidden = true;
    trigger.hidden = false;
    trigger.focus();
  }

  function submitInlineEdit(form, trigger, feedback) {
    if (form.dataset.busy === "true" || !form.reportValidity()) {
      return;
    }
    form.dataset.busy = "true";
    form.querySelectorAll("button").forEach(function (button) {
      button.disabled = true;
    });

    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json" },
    })
      .then(readJsonResponse)
      .then(function (result) {
        if (result.ok && result.data && result.data.date) {
          showSessionDetails(result.data);
          const input = form.querySelector("input");
          input.defaultValue = input.value = input.name === "date" ? result.data.date : result.data.name;
          form.hidden = true;
          trigger.hidden = false;
          trigger.focus();
          showMessage(feedback, result.data.message, "success");
        } else {
          // The form stays open with the typed value.
          showMessage(
            feedback,
            errorMessage(result, "Não foi possível salvar. Tente novamente.", "Este treino não existe mais. Recarregue a página."),
            "error"
          );
        }
      })
      .catch(function () {
        showMessage(feedback, "Não foi possível conectar ao servidor. Tente novamente.", "error");
      })
      .finally(function () {
        delete form.dataset.busy;
        form.querySelectorAll("button").forEach(function (button) {
          button.disabled = false;
        });
      });
  }

  // Values come from the server's answer and are inserted as text.
  function showSessionDetails(details) {
    document.querySelectorAll("[data-session-name]").forEach(function (element) {
      element.textContent = details.name;
    });
    document.querySelectorAll("[data-session-date]").forEach(function (element) {
      element.textContent = details.date_label;
      element.setAttribute("datetime", details.date);
    });
    document.title = details.name + " | Workout Tracker";
  }

  // ---------------------------------------------------------------------------
  // 8. Warning before leaving with values not saved
  // ---------------------------------------------------------------------------

  // Repetitions and weight typed in a set form, and a name or date typed in
  // place, are saved only when their form is sent. Every input keeps the value
  // rendered by the server as its defaultValue (a saved change renders new
  // inputs, or updates it for the name and date), so a different value has not
  // been saved. Leaving the page then asks the browser to confirm, with its
  // own message. Opening, closing or cancelling forms changes nothing saved,
  // and a page form sent by the browser (completing or deleting the workout,
  // after confirmation) leaves on purpose, so neither asks.
  function setUpUnsavedValuesWarning() {
    if (!document.querySelector("[data-set-form], [data-inline-edit]")) {
      return;
    }
    let leavingWithForm = false;

    // Registered after the other submit listeners: a submission they send
    // with fetch() is already defaultPrevented; any other one loads a page.
    document.addEventListener("submit", function (event) {
      if (!event.defaultPrevented) {
        leavingWithForm = true;
      }
    });
    window.addEventListener("pageshow", function (event) {
      if (event.persisted) {
        leavingWithForm = false;
      }
    });

    window.addEventListener("beforeunload", function (event) {
      if (!leavingWithForm && hasUnsavedValues()) {
        event.preventDefault();
        // Older browsers only ask when returnValue is set.
        event.returnValue = "";
      }
    });
  }

  function hasUnsavedValues() {
    const inputs = document.querySelectorAll(
      '[data-set-form] input:not([type="hidden"]), [data-inline-edit] input:not([type="hidden"])'
    );
    return Array.prototype.some.call(inputs, function (input) {
      return input.value !== input.defaultValue;
    });
  }
})();
