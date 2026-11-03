/* Shared SCORM 1.2 / 2004 runtime shim.
 *
 * Auto-detects the SCORM API version at runtime by walking the parent frame
 * chain for API_1484_11 (2004) before falling back to API (1.2) -- the
 * standard SCORM API-discovery algorithm. The same rendered page therefore
 * works unmodified against either a SCORM 1.2 or SCORM 2004 manifest; only
 * imsmanifest.xml needs to differ per version.
 */
var ScormShim = (function () {
  var api = null;
  var version = null; // '1.2' | '2004'

  function findAPI(win, depth) {
    depth = depth || 0;
    if (!win || depth > 10) return null;
    try {
      if (win.API_1484_11) return { api: win.API_1484_11, version: '2004' };
      if (win.API) return { api: win.API, version: '1.2' };
    } catch (e) {
      return null;
    }
    if (win.parent && win.parent !== win) return findAPI(win.parent, depth + 1);
    return null;
  }

  function init() {
    var found = findAPI(window) || (window.opener && findAPI(window.opener));
    if (!found) return false;
    api = found.api;
    version = found.version;
    try {
      version === '2004' ? api.Initialize('') : api.LMSInitialize('');
    } catch (e) {}
    return true;
  }

  function isActive() {
    return !!api;
  }

  function getVersion() {
    return version;
  }

  function get(key12, key2004) {
    if (!api) return '';
    try {
      return version === '2004' ? api.GetValue(key2004) : api.LMSGetValue(key12);
    } catch (e) {
      return '';
    }
  }

  function set(key12, key2004, value) {
    if (!api) return;
    try {
      version === '2004' ? api.SetValue(key2004, value) : api.LMSSetValue(key12, value);
    } catch (e) {}
  }

  function commit() {
    if (!api) return;
    try {
      version === '2004' ? api.Commit('') : api.LMSCommit('');
    } catch (e) {}
  }

  function terminate() {
    if (!api) return;
    try {
      version === '2004' ? api.Terminate('') : api.LMSFinish('');
    } catch (e) {}
  }

  function getLearnerName() {
    return get('cmi.core.student_name', 'cmi.learner_name');
  }

  function getSuspendData() {
    return get('cmi.suspend_data', 'cmi.suspend_data');
  }

  function setSuspendData(value) {
    set('cmi.suspend_data', 'cmi.suspend_data', value);
  }

  /* Normalized completion/success read: 'completed'|'passed'|'failed'|'incomplete'|'' */
  function getStatus() {
    if (!api) return '';
    if (version === '2004') {
      var success = get('', 'cmi.success_status');
      if (success === 'passed' || success === 'failed') return success;
      return get('', 'cmi.completion_status');
    }
    return get('cmi.core.lesson_status', '');
  }

  function setIncomplete() {
    if (version === '2004') set('', 'cmi.completion_status', 'incomplete');
    else set('cmi.core.lesson_status', '', 'incomplete');
  }

  function setCompleted() {
    if (version === '2004') set('', 'cmi.completion_status', 'completed');
    else set('cmi.core.lesson_status', '', 'completed');
  }

  /* percent: 0-100 */
  function setResult(passed, percent) {
    if (version === '2004') {
      set('', 'cmi.completion_status', 'completed');
      set('', 'cmi.success_status', passed ? 'passed' : 'failed');
      set('', 'cmi.score.raw', String(percent));
      set('', 'cmi.score.min', '0');
      set('', 'cmi.score.max', '100');
      set('', 'cmi.score.scaled', String(percent / 100));
    } else {
      set('cmi.core.lesson_status', '', passed ? 'passed' : 'failed');
      set('cmi.core.score.raw', '', String(percent));
      set('cmi.core.score.min', '', '0');
      set('cmi.core.score.max', '', '100');
    }
  }

  function recordInteraction(idx, id, response, correctPattern, correct) {
    var b = 'cmi.interactions.' + idx + '.';
    set(b + 'id', b + 'id', id);
    set(b + 'type', b + 'type', 'choice');
    if (version === '2004') {
      set('', b + 'learner_response', String(response));
      set('', b + 'result', correct ? 'correct' : 'incorrect');
    } else {
      set(b + 'student_response', '', String(response));
      set(b + 'result', '', correct ? 'correct' : 'wrong');
    }
    set(b + 'correct_responses.0.pattern', b + 'correct_responses.0.pattern', String(correctPattern));
    set(b + 'weighting', b + 'weighting', '1');
  }

  window.addEventListener('beforeunload', function () {
    if (api) terminate();
  });

  return {
    init: init,
    isActive: isActive,
    getVersion: getVersion,
    get: get,
    set: set,
    commit: commit,
    terminate: terminate,
    getLearnerName: getLearnerName,
    getSuspendData: getSuspendData,
    setSuspendData: setSuspendData,
    getStatus: getStatus,
    setIncomplete: setIncomplete,
    setCompleted: setCompleted,
    setResult: setResult,
    recordInteraction: recordInteraction
  };
})();
