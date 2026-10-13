// Workout template builder (workout_templates/new.html).
//
// The page renders every muscle group and its exercises; this file switches
// between the groups view and one group's exercises without reloading, so the
// name and the selected exercises stay in memory while the template is built.
//
// Exercise cards open the shared exercise modal (exercise_history.js). Its
// "Adicionar" button adds the opened exercise to the selection and returns to
// the muscle groups. Nothing is saved until "Criar modelo", which sends the
// name and the exercise ids, in order, to POST /templates; the server
// validates everything and a rejected request keeps the page as it was.
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
  const errorElement = form.querySelector("[data-builder-error]");
  const submitButton = form.querySelector("[data-builder-submit]");
  const addButton = dialog.querySelector("[data-exercise-add]");

  // Selected exercises in template order: { id, name, subgroup }.
  const selection = [];
  // The exercise shown in the modal, taken from the card that opened it.
  let openedExercise = null;
  let submitting = false;

  selectedTitle.tabIndex = -1;
  renderSelection();

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
  // Selected exercises: order, move and remove
  // ---------------------------------------------------------------------------

  function changeSelection(action, index) {
    const exercise = selection[index];
    if (!exercise) {
      return;
    }

    let focusIndex = index;
    if (action === "up" && index > 0) {
      selection.splice(index, 1);
      selection.splice(index - 1, 0, exercise);
      focusIndex = index - 1;
    } else if (action === "down" && index < selection.length - 1) {
      selection.splice(index, 1);
      selection.splice(index + 1, 0, exercise);
      focusIndex = index + 1;
    } else if (action === "remove") {
      selection.splice(index, 1);
      showFeedback(exercise.name + " removido do modelo.");
    } else {
      return;
    }

    renderSelection();
    restoreFocus(action, focusIndex);
  }

  // The list is rebuilt after each change, so focus goes to the equivalent
  // control: the same arrow on the moved exercise (or the other arrow when it
  // reached an end), or the next "Remover" after a removal.
  function restoreFocus(action, index) {
    if (selection.length === 0) {
      selectedTitle.focus();
      return;
    }
    const item = selectedList.children[Math.min(index, selection.length - 1)];
    const preferred = action === "remove" ? ["remove"] : [action, action === "up" ? "down" : "up", "remove"];
    for (const name of preferred) {
      const button = item.querySelector('[data-selection-action="' + name + '"]');
      if (button) {
        button.focus();
        return;
      }
    }
  }

  function renderSelection() {
    selectedList.replaceChildren(
      ...selection.map(function (exercise, index) {
        return buildSelectedItem(exercise, index);
      })
    );
    selectedCount.textContent = String(selection.length);
    selectedEmpty.hidden = selection.length > 0;
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

    const actions = document.createElement("div");
    actions.className = "actions";
    if (index > 0) {
      actions.appendChild(buildActionButton("up", index, "↑", "Mover " + exercise.name + " para cima", "btn-secondary btn-icon"));
    }
    if (index < selection.length - 1) {
      actions.appendChild(buildActionButton("down", index, "↓", "Mover " + exercise.name + " para baixo", "btn-secondary btn-icon"));
    }
    actions.appendChild(buildActionButton("remove", index, "Remover", "Remover " + exercise.name, "btn-danger"));

    item.append(position, text, actions);
    return item;
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
  // "Criar modelo"
  // ---------------------------------------------------------------------------

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (submitting) {
      return;
    }
    setSubmitting(true);
    hideError();

    const data = new FormData();
    data.append("name", nameInput.value);
    selection.forEach(function (exercise) {
      data.append("exercise_ids", String(exercise.id));
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
            return { ok: response.ok, data: result };
          });
      })
      .then(function (result) {
        if (result.ok && result.data && result.data.redirect_url) {
          // The button stays disabled while the next page loads.
          window.location.assign(result.data.redirect_url);
          return;
        }
        showError((result.data && result.data.error) || "Não foi possível criar o modelo. Tente novamente.");
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
    }
  });

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
