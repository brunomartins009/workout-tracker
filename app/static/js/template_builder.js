// Workout template builder (workout_templates/form.html), used to create a
// template and to edit one.
//
// The page renders every muscle group and its exercises; this file switches
// between the groups view and one group's exercises without reloading, so the
// name, the selected exercises, their order and their targets stay in memory
// while the template is built. When editing, the current exercises and
// targets are the initial selection.
//
// Exercise cards open the shared exercise modal (exercise_history.js). Its
// "Adicionar" button adds the opened exercise to the selection, with default
// targets, and returns to the muscle groups. Exercises are reordered by
// dragging their handle (sortable_list.js) or with the arrow keys on it.
// Nothing is saved until the form is submitted: the name and, for each
// exercise in order, its id, target sets and target repetitions are sent to
// the form's action; the server validates everything and a rejected request
// keeps the page as it was.
//
// Exercise names are inserted with textContent, never as HTML.
(function () {
  "use strict";

  const form = document.querySelector("[data-template-builder]");
  const dialog = document.getElementById("exercise-history-dialog");
  if (!form || !dialog) {
    return;
  }

  const nameInput = form.querySelector('input[name="name"]');
  const pickerTitle = document.getElementById("exercise-picker-title");
  const groupsView = form.querySelector("[data-builder-groups]");
  const groupViews = form.querySelectorAll("[data-builder-group]");
  const feedback = form.querySelector("[data-builder-feedback]");
  const selectedTitle = document.getElementById("selected-exercises-title");
  const selectedList = form.querySelector("[data-selected-list]");
  const selectedCount = form.querySelector("[data-selected-count]");
  const selectedEmpty = form.querySelector("[data-selected-empty]");
  const selectedHint = form.querySelector("[data-selected-hint]");
  const errorElement = form.querySelector("[data-builder-error]");
  const submitButton = form.querySelector("[data-builder-submit]");
  const addButton = dialog.querySelector("[data-exercise-add]");

  // Targets of an exercise just added; they can be changed in the list.
  const DEFAULT_TARGET_SETS = "3";
  const DEFAULT_TARGET_REPETITIONS = "10";
  const targetLimits = {
    targetSets: Number(form.dataset.targetSetsMax),
    targetRepetitions: Number(form.dataset.targetRepetitionsMax),
  };

  // Selected exercises in template order:
  // { id, name, subgroup, targetSets, targetRepetitions } (targets as typed).
  const selection = readInitialSelection();
  // The exercise shown in the modal, taken from the card that opened it.
  let openedExercise = null;
  let submitting = false;

  // What the template is when the page opens (empty when creating): leaving
  // the page with anything else asks the browser to confirm.
  const savedState = currentState();
  let leavingAfterSave = false;

  selectedTitle.tabIndex = -1;
  renderSelection();

  window.SortableList.attach(selectedList, {
    handleSelector: "[data-drag-handle]",
    onMove: moveExercise,
  });

  // When editing, the page brings the template's exercises; a target saved
  // before targets existed comes empty and must be filled in before saving.
  function readInitialSelection() {
    const source = document.getElementById("template-builder-initial");
    const items = source ? JSON.parse(source.textContent) : [];
    return items.map(function (item) {
      return {
        id: item.id,
        name: item.name,
        subgroup: item.subgroup,
        targetSets: item.target_sets === null ? "" : String(item.target_sets),
        targetRepetitions: item.target_repetitions === null ? "" : String(item.target_repetitions),
      };
    });
  }

  // A validation message refers to what was sent; it goes away once the user
  // changes the name (here) or the selection (in renderSelection).
  nameInput.addEventListener("input", hideError);

  // ---------------------------------------------------------------------------
  // Picker: muscle groups -> exercises of a group -> exercise modal
  // ---------------------------------------------------------------------------

  form.addEventListener("click", function (event) {
    const groupButton = event.target.closest("[data-builder-show-group]");
    if (groupButton) {
      showGroup(groupButton.dataset.builderShowGroup);
      return;
    }

    const backButton = event.target.closest("[data-builder-show-groups]");
    if (backButton) {
      const groupId = backButton.closest("[data-builder-group]").id;
      showGroups();
      // Back where the user was: the card of the group just left.
      form.querySelector('[data-builder-show-group="' + groupId + '"]').focus();
      return;
    }

    // exercise_history.js opens the modal from the same click; this only
    // remembers which exercise "Adicionar" refers to.
    const exerciseCard = event.target.closest("[data-exercise-id]");
    if (exerciseCard) {
      openedExercise = {
        id: Number(exerciseCard.dataset.exerciseId),
        name: exerciseCard.dataset.exerciseName,
        subgroup: exerciseCard.dataset.exerciseSubgroup,
        targetSets: DEFAULT_TARGET_SETS,
        targetRepetitions: DEFAULT_TARGET_REPETITIONS,
      };
      updateAddButton();
      return;
    }

    const selectionButton = event.target.closest("[data-selection-action]");
    if (selectionButton) {
      changeSelection(selectionButton.dataset.selectionAction, Number(selectionButton.dataset.index));
    }
  });

  function showGroup(groupId) {
    groupsView.hidden = true;
    groupViews.forEach(function (groupView) {
      groupView.hidden = groupView.id !== groupId;
    });
    document.getElementById(groupId).querySelector(".builder-group-title").focus();
  }

  function showGroups() {
    groupViews.forEach(function (groupView) {
      groupView.hidden = true;
    });
    groupsView.hidden = false;
  }

  addButton.addEventListener("click", function () {
    if (!openedExercise || isSelected(openedExercise.id)) {
      return;
    }
    const added = openedExercise;
    selection.push(added);
    renderSelection();
    dialog.close();
    showGroups();
    pickerTitle.focus();
    showFeedback(added.name + " adicionado ao modelo.");
  });

  dialog.addEventListener("close", function () {
    openedExercise = null;
  });

  // An exercise already in the template cannot be added again.
  function updateAddButton() {
    const alreadySelected = isSelected(openedExercise.id);
    addButton.disabled = alreadySelected;
    addButton.textContent = alreadySelected ? "Adicionado" : "Adicionar";
  }

  function isSelected(exerciseId) {
    return selection.some(function (exercise) {
      return exercise.id === exerciseId;
    });
  }

  // ---------------------------------------------------------------------------
  // Selected exercises: targets, order and removal
  // ---------------------------------------------------------------------------

  // Targets are kept as typed; the browser checks them before saving and the
  // server validates them again.
  selectedList.addEventListener("input", function (event) {
    const input = event.target.closest("[data-target]");
    if (input) {
      selection[Number(input.dataset.index)][input.dataset.target] = input.value;
      hideError();
    }
  });

  function moveExercise(from, to) {
    const exercise = selection.splice(from, 1)[0];
    selection.splice(to, 0, exercise);
    renderSelection();
    // The list was redrawn: keep the focus on the moved exercise's handle, so
    // the arrow keys can keep moving it.
    selectedList.children[to].querySelector("[data-drag-handle]").focus({ preventScroll: true });
    showFeedback(exercise.name + " movido para a posição " + (to + 1) + ".");
  }

  function changeSelection(action, index) {
    const exercise = selection[index];
    if (!exercise || action !== "remove") {
      return;
    }
    selection.splice(index, 1);
    showFeedback(exercise.name + " removido do modelo.");
    renderSelection();
    // Focus goes to the next "Remover", or to the list title when empty.
    if (selection.length === 0) {
      selectedTitle.focus();
      return;
    }
    const item = selectedList.children[Math.min(index, selection.length - 1)];
    item.querySelector('[data-selection-action="remove"]').focus();
  }

  function renderSelection() {
    selectedList.replaceChildren(
      ...selection.map(function (exercise, index) {
        return buildSelectedItem(exercise, index);
      })
    );
    selectedCount.textContent = String(selection.length);
    selectedEmpty.hidden = selection.length > 0;
    selectedHint.hidden = selection.length === 0;
    hideError();

    // Mark the library cards of the selected exercises.
    form.querySelectorAll("[data-exercise-id]").forEach(function (card) {
      const selected = isSelected(Number(card.dataset.exerciseId));
      card.classList.toggle("is-selected", selected);
      card.querySelector("[data-selected-mark]").hidden = !selected;
    });
  }

  function buildSelectedItem(exercise, index) {
    const item = document.createElement("li");
    item.className = "selected-exercise";

    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = "drag-handle";
    handle.dataset.dragHandle = "";
    handle.textContent = "⠿";
    handle.setAttribute(
      "aria-label",
      "Reordenar " + exercise.name + ", posição " + (index + 1) + " de " + selection.length +
        ". Arraste ou use as setas para cima e para baixo."
    );
    handle.title = "Arraste para reordenar";

    const position = document.createElement("span");
    position.className = "position-badge";
    position.setAttribute("aria-hidden", "true");
    position.textContent = String(index + 1);

    const text = document.createElement("span");
    text.className = "selected-exercise-text";
    const name = document.createElement("span");
    name.className = "selected-exercise-name";
    name.textContent = exercise.name;
    const subgroup = document.createElement("span");
    subgroup.className = "selected-exercise-subgroup";
    subgroup.textContent = exercise.subgroup;
    text.append(name, subgroup);

    const targets = document.createElement("div");
    targets.className = "selected-exercise-targets";
    targets.append(
      buildTargetField(exercise, index, "targetSets", "Séries"),
      buildTargetField(exercise, index, "targetRepetitions", "Reps/série")
    );

    const actions = document.createElement("div");
    actions.className = "actions";
    actions.appendChild(buildActionButton("remove", index, "Remover", "Remover " + exercise.name, "btn-danger"));

    item.append(handle, position, text, targets, actions);
    return item;
  }

  function buildTargetField(exercise, index, target, labelText) {
    const field = document.createElement("label");
    field.className = "target-field";
    const label = document.createElement("span");
    label.className = "target-field-label";
    label.textContent = labelText;
    const input = document.createElement("input");
    input.type = "number";
    input.inputMode = "numeric";
    input.min = "1";
    input.max = String(targetLimits[target]);
    input.step = "1";
    input.required = true;
    input.value = exercise[target];
    input.dataset.target = target;
    input.dataset.index = String(index);
    input.setAttribute("aria-label", labelText + " de " + exercise.name);
    field.append(label, input);
    return field;
  }

  function buildActionButton(action, index, label, accessibleName, classes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-small " + classes;
    button.dataset.selectionAction = action;
    button.dataset.index = String(index);
    button.textContent = label;
    button.setAttribute("aria-label", accessibleName);
    button.title = accessibleName;
    return button;
  }

  // ---------------------------------------------------------------------------
  // "Criar modelo" / "Salvar alterações"
  // ---------------------------------------------------------------------------

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (submitting) {
      return;
    }
    // Shows the browser's message on the first empty or out-of-range field
    // (name and targets) before anything is sent.
    if (!form.reportValidity()) {
      return;
    }
    setSubmitting(true);
    hideError();

    const data = new FormData();
    data.append("name", nameInput.value);
    selection.forEach(function (exercise) {
      data.append("exercise_ids", String(exercise.id));
      data.append("target_sets", exercise.targetSets);
      data.append("target_repetitions", exercise.targetRepetitions);
    });

    fetch(form.action, {
      method: "POST",
      body: data,
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return null;
          })
          .then(function (result) {
            return { ok: response.ok, status: response.status, data: result };
          });
      })
      .then(function (result) {
        if (result.ok && result.data && result.data.redirect_url) {
          // The button stays disabled while the next page loads.
          leavingAfterSave = true;
          window.location.assign(result.data.redirect_url);
          return;
        }
        if (result.data && result.data.error) {
          showError(result.data.error);
        } else if (result.status === 404) {
          // An HTML page, without JSON: the template was deleted meanwhile.
          showError("Este modelo não existe mais. Ele pode ter sido excluído em outra aba.");
        } else {
          showError("Não foi possível salvar o modelo. Tente novamente.");
        }
        setSubmitting(false);
      })
      .catch(function () {
        showError("Não foi possível conectar ao servidor. Tente novamente.");
        setSubmitting(false);
      });
  });

  // Coming back with the browser's Back button may restore the page as it was
  // left, with the button still disabled.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      setSubmitting(false);
      leavingAfterSave = false;
    }
  });

  // ---------------------------------------------------------------------------
  // Warning before leaving with changes not saved
  // ---------------------------------------------------------------------------

  // The name, the exercises, their order and their targets live only in this
  // page until saved. Changing something and changing it back is not a change;
  // moving between muscle groups or opening the modal changes nothing.
  window.addEventListener("beforeunload", function (event) {
    if (!leavingAfterSave && currentState() !== savedState) {
      event.preventDefault();
      // Older browsers only ask when returnValue is set.
      event.returnValue = "";
    }
  });

  // Compared as the server will read it: the name without surrounding spaces.
  function currentState() {
    return JSON.stringify({
      name: nameInput.value.trim(),
      exercises: selection.map(function (exercise) {
        return [exercise.id, exercise.targetSets, exercise.targetRepetitions];
      }),
    });
  }

  function setSubmitting(value) {
    submitting = value;
    submitButton.disabled = value;
  }

  function showError(message) {
    errorElement.textContent = message;
    errorElement.hidden = false;
    errorElement.scrollIntoView({ block: "nearest" });
  }

  function hideError() {
    errorElement.textContent = "";
    errorElement.hidden = true;
  }

  function showFeedback(message) {
    window.clearTimeout(Number(feedback.dataset.timeout));
    feedback.textContent = message;
    feedback.dataset.timeout = String(
      window.setTimeout(function () {
        feedback.textContent = "";
      }, 4000)
    );
  }
})();
