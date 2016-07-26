/* global jQuery, window */

const $ = jQuery;

function getForm() {
  return $('[data-step1-form]')[0];
}

function replaceForm(html) {
  // Replace the form and bind it.
  $(getForm()).replaceWith(html);

  // Animate the new form so the user notices it.
  // TODO: Consider using a CSS class w/ a transition or animation instead.
  $(getForm()).hide().fadeIn();
}

function bindForm() {
  const form = getForm();
  const $upload = $('.upload', form);

  if (!form) {
    // We're not on step 1.
    return;
  }

  $upload.uploadify();
  $(form).on('submit', (e) => {
    const $uploadInput = $('input', $upload);
    const upload = $uploadInput.data('upload');

    if (upload.isDegraded) {
      // The upload widget is degraded; we should assume the browser has
      // minimal HTML5 support and just let the user submit the form manually.
    } else {
      e.preventDefault();

      const formData = new window.FormData(form);

      if (upload.file) {
        // It's possible that the user may have dragged-and-dropped a
        // file to our upload widget, in which case the actual
        // file <input> element won't contain what we want. So we'll remove
        // whatever may have come from that <input> and replace it
        // with the file the upload widget says we need to upload.
        formData.delete($uploadInput.attr('name'));
        formData.append($uploadInput.attr('name'), upload.file);
      }

      const req = $.ajax(form.action, {
        processData: false,
        contentType: false,
        data: formData,
        method: form.method,
      });

      // TODO: Use a CSS class to do this. Add a throbber or progress
      // bar or something.
      $(form).css({ opacity: 0.25, 'pointer-events': 'none' });

      req.done((data) => {
        if (data.form_html) {
          replaceForm(data.form_html);
          bindForm();
        } else if (data.redirect_url) {
          window.location = data.redirect_url;
        } else {
          // TODO: Be more user-friendly here.
          window.alert( // eslint-disable-line no-alert
            `Invalid server response: ${data}`
          );
        }
      });

      req.fail(() => {
        // TODO: Be more user-friendly here.
        window.alert( // eslint-disable-line no-alert
          'An error occurred when submitting your data.'
        );
      });
    }
  });
}

$(bindForm);
