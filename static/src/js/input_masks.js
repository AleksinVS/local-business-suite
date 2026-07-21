/* Phone and date masks for waiting list forms */
function applyPhoneMask(input) {
  var value = input.value.replace(/\D/g, '');
  if (value.length >= 1) {
    var formatted = '+7';
    if (value.length > 1) {
      formatted += ' (' + value.substring(1, 4);
    }
    if (value.length > 4) {
      formatted += ') ' + value.substring(4, 7);
    }
    if (value.length > 7) {
      formatted += '-' + value.substring(7, 9);
    }
    if (value.length > 9) {
      formatted += '-' + value.substring(9, 11);
    }
    input.value = formatted;
  }
}

function applyDobMask(input) {
  var value = input.value.replace(/\D/g, '').slice(0, 8);
  if (value.length >= 5) {
    input.value = value.slice(0, 2) + '.' + value.slice(2, 4) + '.' + value.slice(4);
  } else if (value.length >= 3) {
    input.value = value.slice(0, 2) + '.' + value.slice(2);
  } else {
    input.value = value;
  }
}

function initInputMasks() {
  var phoneInputs = document.querySelectorAll('[data-phone-mask]');
  phoneInputs.forEach(function(input) {
    input.addEventListener('input', function(e) { applyPhoneMask(e.target); });
  });
  var dobInputs = document.querySelectorAll('[data-dob-mask]');
  dobInputs.forEach(function(input) {
    input.addEventListener('input', function(e) { applyDobMask(e.target); });
  });
}

document.addEventListener('DOMContentLoaded', initInputMasks);
document.addEventListener('htmx:afterSettle', initInputMasks);