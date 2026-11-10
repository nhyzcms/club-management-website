(function () {
  function csrfToken() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  }

  function setStatus(text) {
    var status = document.getElementById("survey-save-status");
    if (status) status.textContent = text;
  }

  function postSchema(url, schema, done) {
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify({ schema: schema }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { httpOk: r.ok, data: data };
        });
      })
      .then(function (res) {
        var ok = !!(res.httpOk && res.data && res.data.ok);
        done(ok, (res.data && res.data.error) || "");
      })
      .catch(function () {
        done(false, "保存失败");
      });
  }

  window.SurveyAdminEditor = {
    init: function (opts) {
      var schemaEl = document.getElementById(opts.schemaEl);
      var schema = JSON.parse(schemaEl.textContent);
      if (Survey.surveyLocalization) {
        Survey.surveyLocalization.defaultLocale = "zh-cn";
        Survey.surveyLocalization.currentLocale = "zh-cn";
      }
      if (SurveyCreatorCore && SurveyCreatorCore.editorLocalization) {
        SurveyCreatorCore.editorLocalization.defaultLocale = "zh-cn";
        SurveyCreatorCore.editorLocalization.currentLocale = "zh-cn";
      }
      var creator = new SurveyCreator.SurveyCreator({ showLogicTab: true, locale: "zh-cn" });
      creator.locale = "zh-cn";
      creator.JSON = schema;
      creator.saveSurveyFunc = function (saveNo, callback) {
        if (!opts.canSave) {
          callback(saveNo, false);
          return;
        }
        postSchema(opts.saveUrl, creator.JSON, function (ok, error) {
          callback(saveNo, ok);
          setStatus(ok ? "已保存" : error || "保存失败");
        });
      };
      creator.render("survey-creator");

      var saveBtn = document.getElementById("survey-save");
      if (saveBtn) {
        saveBtn.addEventListener("click", function () {
          postSchema(opts.saveUrl, creator.JSON, function (ok, error) {
            setStatus(ok ? "已保存" : error || "保存失败");
          });
        });
      }
    },
  };
})();
