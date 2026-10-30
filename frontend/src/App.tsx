import { HashRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { lazy, Suspense, useEffect, type ReactElement } from "react";
import ProtectedRoute from "./components/ProtectedRoute";
import SessionGuard from "./components/SessionGuard";
import ValidityNoticeHost from "./components/ValidityNoticeHost";
import AnnouncementHost from "./components/AnnouncementHost";
import LoginModalProvider from "./components/LoginModalProvider";
import MascotHost from "./components/mascot/MascotHost";
import { useEmbedMode } from "./embed";
import { api } from "./api/client";
import { fetchSitePolicy } from "./api/sitePolicy";
import { isMobileDevice } from "./utils/device";

const ForgotPasswordPage = lazy(() => import("./pages/ForgotPasswordPage"));
const ForcePasswordChangePage = lazy(() => import("./pages/ForcePasswordChangePage"));
const ResetPasswordPage = lazy(() => import("./pages/ResetPasswordPage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const VerifyEmailPage = lazy(() => import("./pages/VerifyEmailPage"));
const VerifyEmailPendingPage = lazy(() => import("./pages/VerifyEmailPendingPage"));
const MemberVerifyPage = lazy(() => import("./pages/MemberVerifyPage"));
const MemberLookupPage = lazy(() => import("./pages/MemberLookupPage"));
const SecurityCenterPage = lazy(() => import("./pages/SecurityCenterPage"));
const StepUpPage = lazy(() => import("./pages/StepUpPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const UserProfile = lazy(() => import("./pages/UserProfile"));
const ProfileRedirect = lazy(() => import("./pages/ProfileRedirect"));
const TaskListPage = lazy(() => import("./pages/TaskListPage"));
const TaskDetailPage = lazy(() => import("./pages/TaskDetailPage"));
const TaskFormPage = lazy(() => import("./pages/TaskFormPage"));
const MessagePage = lazy(() => import("./pages/MessagePage"));
const NotificationsPage = lazy(() => import("./pages/NotificationsPage"));
const AnnouncementPage = lazy(() => import("./pages/AnnouncementPage"));
const FeedbackPage = lazy(() => import("./pages/FeedbackPage"));
const FeedbackDetailPage = lazy(() => import("./pages/FeedbackDetailPage"));
const ActivityListPage = lazy(() => import("./pages/ActivityListPage"));
const ActivityFormPage = lazy(() => import("./pages/ActivityFormPage"));
const ActivityDetailPage = lazy(() => import("./pages/ActivityDetailPage"));
const EventsPage = lazy(() => import("./pages/EventsPage"));
const EventDetailPage = lazy(() => import("./pages/EventDetailPage"));
const EventFormPage = lazy(() => import("./pages/EventFormPage"));
const InboxPage = lazy(() => import("./pages/InboxPage"));
const NewsListPage = lazy(() => import("./pages/NewsListPage"));
const NewsDetailPage = lazy(() => import("./pages/NewsDetailPage"));
const NewsFormPage = lazy(() => import("./pages/NewsFormPage"));
const ReviewQueuePage = lazy(() => import("./pages/ReviewQueuePage"));
const AboutPage = lazy(() => import("./pages/AboutPage"));
const PanoramaPage = lazy(() => import("./pages/PanoramaPage"));
const PanoramaManagePage = lazy(() => import("./pages/PanoramaManagePage"));
const ExamBoardPage = lazy(() => import("./pages/ExamBoardPage"));
const SchedulePage = lazy(() => import("./pages/SchedulePage"));
const TutorialListPage = lazy(() => import("./pages/TutorialListPage"));
const TutorialDetailPage = lazy(() => import("./pages/TutorialDetailPage"));
const TutorialFormPage = lazy(() => import("./pages/TutorialFormPage"));
const JoinPage = lazy(() => import("./pages/JoinPage"));
const JoinFormPage = lazy(() => import("./pages/JoinFormPage"));
const JoinEditorPage = lazy(() => import("./pages/JoinEditorPage"));
const SurveyEditorPage = lazy(() => import("./pages/SurveyEditorPage"));
const SurveyResponsesPage = lazy(() => import("./pages/SurveyResponsesPage"));
const SurveyStatsPage = lazy(() => import("./pages/SurveyStatsPage"));
const MobileHomePage = lazy(() => import("./pages/MobileHomePage"));
const MobileNewsPage = lazy(() => import("./pages/MobileNewsPage"));
const MobileActivityPage = lazy(() => import("./pages/MobileActivityPage"));
const MobileMePage = lazy(() => import("./pages/MobileMePage"));
const MobileNewsDetailPage = lazy(() => import("./pages/MobileNewsDetailPage"));
const MobileActivityDetailPage = lazy(() => import("./pages/MobileActivityDetailPage"));
const MobileTutorialsPage = lazy(() => import("./pages/MobileTutorialsPage"));
const MobileTutorialDetailPage = lazy(() => import("./pages/MobileTutorialDetailPage"));
const MobileJoinPage = lazy(() => import("./pages/MobileJoinPage"));
const MobileJoinFormPage = lazy(() => import("./pages/MobileJoinFormPage"));
const MobileReviewPage = lazy(() => import("./pages/MobileReviewPage"));
const MobileInboxPage = lazy(() => import("./pages/MobileInboxPage"));
const MobileNotificationsPage = lazy(() => import("./pages/MobileNotificationsPage"));
const MobileTaskListPage = lazy(() => import("./pages/MobileTaskListPage"));
const MobileTaskDetailPage = lazy(() => import("./pages/MobileTaskDetailPage"));

function Loading() {
  return <div style={{ textAlign: "center", padding: "80px 0", color: "#6b7280" }}>加载中…</div>;
}

function MaybeMascot() {
  const embed = useEmbedMode();
  if (embed) return null;
  return <MascotHost />;
}

/** 手机访问站点根路径时直接进入手机版（/#/m）；桌面端与深链接不受影响。 */
function HomeRoute() {
  if (isMobileDevice()) return <Navigate to="/m" replace />;
  return <HomePage />;
}

/**
 * 手机 UA 访问「桌面专属」页面时改走对应手机版（例如 /#/reviews → /#/m/review）。
 *
 * 为什么不在页面内部做响应式：桌面页依赖 AppShell 的顶栏与宽屏栅格，
 * 在 390px 上虽然能显示但交互（行内按钮、分页器、双栏）不适合单手操作。
 * 手机版另有专门实现；桌面 UA 完全不受影响。
 */
function MobileAware({ to, children }: { to: string; children: ReactElement }) {
  if (isMobileDevice()) return <Navigate to={to} replace />;
  return children;
}

/** 任务详情：手机 UA 跳到 /m/tasks/:id（需要带上路由参数）。 */
function TaskDetailRoute() {
  const { id } = useParams<{ id: string }>();
  if (isMobileDevice()) return <Navigate to={`/m/tasks/${id}`} replace />;
  return <TaskDetailPage />;
}

export default function App() {
  // 启动时拉取一次 CSRF cookie。开发态 webpack 直接服务模板、不经 Django 渲染，
  // 无法靠 {% csrf_token %} 下发 cookie，故显式请求该端点，避免匿名 POST 被 403。
  useEffect(() => {
    api.getCsrf().catch(() => {});
    fetchSitePolicy();
  }, []);

  return (
    <HashRouter>
      <LoginModalProvider>
      <SessionGuard>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route
            path="/change-password-required"
            element={<ProtectedRoute><ForcePasswordChangePage /></ProtectedRoute>}
          />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/verify-email-pending" element={<VerifyEmailPendingPage />} />
          <Route path="/v" element={<MemberLookupPage />} />
          <Route path="/v/:code" element={<MemberVerifyPage />} />
          <Route path="/verify" element={<ProtectedRoute><StepUpPage /></ProtectedRoute>} />
          <Route path="/security" element={<ProtectedRoute><SecurityCenterPage /></ProtectedRoute>} />
          <Route path="/profile" element={<ProfileRedirect />} />
          <Route path="/u/:id" element={<UserProfile />} />
          <Route path="/tasks" element={<MobileAware to="/m/tasks"><ProtectedRoute><TaskListPage /></ProtectedRoute></MobileAware>} />
          <Route path="/tasks/new" element={<ProtectedRoute><TaskFormPage /></ProtectedRoute>} />
          <Route path="/tasks/:id" element={<ProtectedRoute><TaskDetailRoute /></ProtectedRoute>} />
          <Route path="/tasks/:id/edit" element={<ProtectedRoute><TaskFormPage /></ProtectedRoute>} />
          <Route path="/messages" element={<ProtectedRoute><MessagePage /></ProtectedRoute>} />
          <Route path="/messages/:id" element={<ProtectedRoute><MessagePage /></ProtectedRoute>} />
          <Route path="/notifications" element={<MobileAware to="/m/notifications"><ProtectedRoute><NotificationsPage /></ProtectedRoute></MobileAware>} />
          {/* 全站公告详情：匿名也能看「全站」受众的公告，鉴权由接口按受众判定 */}
          <Route path="/announcements/:id" element={<AnnouncementPage />} />
          <Route path="/activity" element={<ActivityListPage />} />
          <Route path="/activity/new" element={<ProtectedRoute><ActivityFormPage /></ProtectedRoute>} />
          <Route path="/activity/:id" element={<ActivityDetailPage />} />
          <Route path="/activity/:id/edit" element={<ProtectedRoute><ActivityFormPage /></ProtectedRoute>} />
          <Route path="/activity/:id/survey-edit" element={<ProtectedRoute><SurveyEditorPage /></ProtectedRoute>} />
          <Route path="/activity/:id/survey-responses" element={<ProtectedRoute><SurveyResponsesPage /></ProtectedRoute>} />
          <Route path="/activity/:id/survey-stats" element={<ProtectedRoute><SurveyStatsPage /></ProtectedRoute>} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/events/new" element={<ProtectedRoute><EventFormPage /></ProtectedRoute>} />
          <Route path="/events/:id" element={<EventDetailPage />} />
          <Route path="/inbox" element={<MobileAware to="/m/inbox"><ProtectedRoute><InboxPage /></ProtectedRoute></MobileAware>} />
          <Route path="/feedback" element={<FeedbackPage />} />
          <Route path="/feedback/:id" element={<ProtectedRoute><FeedbackDetailPage /></ProtectedRoute>} />
          <Route path="/news" element={<NewsListPage />} />
          <Route path="/news/new" element={<ProtectedRoute><NewsFormPage /></ProtectedRoute>} />
          <Route path="/news/:id" element={<NewsDetailPage />} />
          <Route path="/news/:id/edit" element={<ProtectedRoute><NewsFormPage /></ProtectedRoute>} />
          <Route path="/reviews" element={<MobileAware to="/m/review"><ProtectedRoute><ReviewQueuePage /></ProtectedRoute></MobileAware>} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/panorama" element={<PanoramaPage />} />
          <Route path="/panorama/manage" element={<ProtectedRoute><PanoramaManagePage /></ProtectedRoute>} />
          <Route path="/exam" element={<ExamBoardPage />} />
          <Route path="/schedule" element={<SchedulePage />} />
          <Route path="/tutorials" element={<TutorialListPage />} />
          <Route path="/tutorials/new" element={<ProtectedRoute><TutorialFormPage /></ProtectedRoute>} />
          <Route path="/tutorials/:id" element={<TutorialDetailPage />} />
          <Route path="/join" element={<JoinPage />} />
          <Route path="/join/form" element={<JoinFormPage />} />
          <Route path="/join/editor" element={<ProtectedRoute><JoinEditorPage /></ProtectedRoute>} />
          <Route path="/" element={<HomeRoute />} />
          <Route path="/m" element={<MobileHomePage />} />
          <Route path="/m/news" element={<MobileNewsPage />} />
          <Route path="/m/news/:id" element={<MobileNewsDetailPage />} />
          <Route path="/m/activity" element={<MobileActivityPage />} />
          <Route path="/m/activity/:id" element={<MobileActivityDetailPage />} />
          <Route path="/m/tutorials" element={<MobileTutorialsPage />} />
          <Route path="/m/tutorials/:id" element={<MobileTutorialDetailPage />} />
          <Route path="/m/join" element={<MobileJoinPage />} />
          <Route path="/m/join/form" element={<MobileJoinFormPage />} />
          <Route path="/m/me" element={<MobileMePage />} />
          <Route path="/m/review" element={<ProtectedRoute><MobileReviewPage /></ProtectedRoute>} />
          <Route path="/m/inbox" element={<ProtectedRoute><MobileInboxPage /></ProtectedRoute>} />
          <Route path="/m/notifications" element={<ProtectedRoute><MobileNotificationsPage /></ProtectedRoute>} />
          <Route path="/m/tasks" element={<ProtectedRoute><MobileTaskListPage /></ProtectedRoute>} />
          <Route path="/m/tasks/:id" element={<ProtectedRoute><MobileTaskDetailPage /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" replace />} />
          
        </Routes>
      </Suspense>
      </SessionGuard>
      {/* 账号有效期弹窗（ADR-0041）：挂在根部，桌面 / 手机版共用同一份快照。 */}
      <ValidityNoticeHost />
      {/* 全站弹窗公告（ADR-0042）：等其它弹窗关掉后再弹，关闭即已读。 */}
      <AnnouncementHost />
      </LoginModalProvider>
      <MaybeMascot />
    </HashRouter>
  );
}
