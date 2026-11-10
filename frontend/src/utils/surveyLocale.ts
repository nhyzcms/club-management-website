import { surveyLocalization } from "survey-core";
import "survey-core/i18n/simplified-chinese";

/** SurveyJS UI locale (简体中文). Import this module for side effects before creating a Model. */
export const SURVEY_LOCALE = "zh-cn";

surveyLocalization.defaultLocale = SURVEY_LOCALE;
surveyLocalization.currentLocale = SURVEY_LOCALE;
