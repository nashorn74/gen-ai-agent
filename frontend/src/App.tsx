// src/App.tsx

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import ChatLayout from "./pages/ChatLayout";
import PrivateRoute from "./components/PrivateRoute";

function App() {
  const token = localStorage.getItem("token");

  // 만약 로그인되지 않았다면 기본 화면은 로그인 페이지로 이동
  // 로그인되어 있으면 /chat으로 이동
  const defaultRoute = token ? "/chat" : "/login";

  return (
    <BrowserRouter>
      <Routes>
        {/* 기본 루트 -> 토큰 있는지 확인 후 /chat or /login */}
        <Route path="/" element={<Navigate to={defaultRoute} replace />} />

        {/* 로그인/회원가입 - 로그인전 상태에서도 접근 가능 */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        {/* 채팅 페이지 - 로그인 안된 경우 접근 불가 */}
        <Route 
          path="/chat"
          element={
            <PrivateRoute>
              <ChatLayout />
            </PrivateRoute>
          }
        />

        {/* Wildcard Not Found */}
        <Route path="*" element={<div>Not Found</div>} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
