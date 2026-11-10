(function () {
  window.SurveyAdminResponse = {
    init: function (opts) {
      var mount = document.getElementById("survey-response");
      var schema = JSON.parse(document.getElementById(opts.schemaEl).textContent);
      var answers = JSON.parse(document.getElementById(opts.answersEl).textContent);
      if (typeof Survey === "undefined") {
        mount.textContent = "SurveyJS 静态资源未复制。请在 frontend/ 运行 npm run copy-surveyjs。";
        return;
      }
      try {
        if (Survey.surveyLocalization) {
          Survey.surveyLocalization.defaultLocale = "zh-cn";
          Survey.surveyLocalization.currentLocale = "zh-cn";
        }
        var survey = new Survey.Model(schema);
        survey.locale = "zh-cn";
        survey.mode = "display";
        survey.questionsOnPageMode = "singlePage";
        survey.showCompletedPage = false;
        survey.data = answers || {};
        if (typeof survey.render === "function") {
          survey.render(mount);
        } else {
          mount.textContent = "无法渲染作答：Survey.Model.render 不可用。";
        }
      } catch (err) {
        mount.textContent = "无法渲染作答：" + (err && err.message ? err.message : err);
      }
    },
  };
})();
