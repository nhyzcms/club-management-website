(function () {
  window.SurveyAdminResults = {
    init: function (opts) {
      var panel = document.getElementById("survey-viz-panel");
      var schema = JSON.parse(document.getElementById(opts.schemaEl).textContent);
      var answers = JSON.parse(document.getElementById(opts.answersEl).textContent);
      if (typeof Survey === "undefined" || typeof SurveyAnalytics === "undefined") {
        panel.textContent = "SurveyJS 静态资源未复制。请在 frontend/ 运行 npm run copy-surveyjs。";
        return;
      }
      if (typeof Chart === "undefined") {
        panel.textContent = "Chart.js 未加载。请在 frontend/ 运行 npm run copy-surveyjs。";
        return;
      }
      if (typeof SurveyAnalytics.Dashboard !== "function") {
        panel.textContent = "无法渲染看板：SurveyAnalytics.Dashboard 不可用。";
        return;
      }
      try {
        var survey = new Survey.Model(schema);
        survey.locale = "zh-cn";
        if (Survey.surveyLocalization) {
          Survey.surveyLocalization.currentLocale = "zh-cn";
        }
        if (SurveyAnalytics.localization) {
          SurveyAnalytics.localization.currentLocale = "zh-cn";
        }
        var vizPanel = new SurveyAnalytics.Dashboard({
          questions: survey.getAllQuestions(),
          data: answers || [],
          allowHideQuestions: true,
        });
        vizPanel.render(panel);
      } catch (err) {
        panel.textContent = "无法渲染看板：" + (err && err.message ? err.message : err);
      }
    },
  };
})();
