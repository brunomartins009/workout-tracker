// Drag-and-drop reordering of a list, used by the template builder and the
// workout page.
//
// Pointer Events cover mouse, pen and touch with the same code, so no library
// is needed (the HTML5 drag-and-drop API does not work with touch). An item is
// dragged only by its handle, which has `touch-action: none`; the rest of the
// item keeps scrolling and clicking normally. While dragging, the item itself
// moves to the place where it would be dropped and is highlighted, which is
// the indicator of the destination.
//
// The handle also answers to the arrow keys (up/down), so the list can be
// reordered without a pointer.
//
// This file never decides what a move means: it reports (from, to) through
// onMove, and the page updates its data or the server and redraws the list.
// A cancelled gesture puts the item back where it was.
window.SortableList = (function () {
  "use strict";

  const AUTO_SCROLL_EDGE = 60;
  const AUTO_SCROLL_STEP = 12;

  function attach(list, options) {
    const handleSelector = options.handleSelector;
    let drag = null;

    function items() {
      return Array.prototype.filter.call(list.children, function (child) {
        return child.tagName === "LI";
      });
    }

    list.addEventListener("pointerdown", function (event) {
      const handle = event.target.closest(handleSelector);
      if (!handle || !list.contains(handle) || (event.pointerType === "mouse" && event.button !== 0)) {
        return;
      }
      const item = handle.closest("li");
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      drag = { item: item, handle: handle, pointerId: event.pointerId, from: items().indexOf(item) };
      item.classList.add("is-dragging");
      list.classList.add("is-sorting");
    });

    list.addEventListener("pointermove", function (event) {
      if (!drag || event.pointerId !== drag.pointerId) {
        return;
      }
      autoScroll(event.clientY);
      // The item goes before the first other item whose middle is below the
      // pointer, or to the end when there is none.
      const others = items().filter(function (item) {
        return item !== drag.item;
      });
      const next = others.find(function (item) {
        const box = item.getBoundingClientRect();
        return event.clientY < box.top + box.height / 2;
      });
      if (next) {
        if (drag.item.nextElementSibling !== next) {
          list.insertBefore(drag.item, next);
        }
      } else if (others.length && list.lastElementChild !== drag.item) {
        others[others.length - 1].after(drag.item);
      }
    });

    list.addEventListener("pointerup", function (event) {
      finish(event, false);
    });
    list.addEventListener("pointercancel", function (event) {
      finish(event, true);
    });

    function finish(event, cancelled) {
      if (!drag || event.pointerId !== drag.pointerId) {
        return;
      }
      const current = drag;
      drag = null;
      current.item.classList.remove("is-dragging");
      list.classList.remove("is-sorting");
      const to = items().indexOf(current.item);
      if (cancelled) {
        // Back to where it was; nothing is reported.
        const reference = items().filter(function (item) {
          return item !== current.item;
        })[current.from];
        list.insertBefore(current.item, reference || null);
        return;
      }
      if (to !== current.from) {
        options.onMove(current.from, to);
      }
    }

    list.addEventListener("keydown", function (event) {
      const handle = event.target.closest(handleSelector);
      if (!handle || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) {
        return;
      }
      event.preventDefault();
      const from = items().indexOf(handle.closest("li"));
      const to = event.key === "ArrowUp" ? from - 1 : from + 1;
      if (to >= 0 && to < items().length) {
        options.onMove(from, to);
      }
    });
  }

  function autoScroll(clientY) {
    if (clientY < AUTO_SCROLL_EDGE) {
      window.scrollBy(0, -AUTO_SCROLL_STEP);
    } else if (clientY > window.innerHeight - AUTO_SCROLL_EDGE) {
      window.scrollBy(0, AUTO_SCROLL_STEP);
    }
  }

  return { attach: attach };
})();
