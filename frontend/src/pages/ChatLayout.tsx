import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  Button,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Divider,
  Paper,
  TextField,
  Switch,
  FormControlLabel
} from "@mui/material";

interface Message {
  message_id: number;
  role: string;
  content: string;
  created_at: string;
}

function ChatLayout() {
  const navigate = useNavigate();

  const [userName, setUserName] = useState("");
  const [conversations, setConversations] = useState<any[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const [question, setQuestion] = useState("");
  const [searchMode, setSearchMode] = useState(false); // "정보 검색" 토글

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;

    // 1) me
    fetch("http://localhost:8000/auth/me", {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => setUserName(data.username))
      .catch((err) => console.error("get me:", err));

    // 2) conversation list
    fetch("http://localhost:8000/chat/conversations", {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => setConversations(data))
      .catch((err) => console.error("get convos:", err));
  }, []);

  // load messages when selectedConversation changes
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;

    if (!selectedConversation) {
      // no conversation selected => clear messages
      setMessages([]);
      return;
    }

    // fetch conversation detail
    fetch(`http://localhost:8000/chat/conversations/${selectedConversation}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => setMessages(data.messages))
      .catch((err) => console.error("get conv detail error:", err));
  }, [selectedConversation]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/login");
  };

  // 새 대화 시작 -> conversation_id=null, messages=[]
  const handleNewConversation = () => {
    setSelectedConversation(null);
    setMessages([]);
  };

  const handleAsk = async () => {
    const token = localStorage.getItem("token");
    if (!token) return;

    try {
      const endpoint = searchMode
        ? "http://localhost:8000/search"
        : "http://localhost:8000/chat";

      const bodyData: any = {
        // if searchMode => { query, conversation_id }
        // else => { question, conversation_id }
        conversation_id: selectedConversation
      };
      if (searchMode) {
        bodyData.query = question; 
      } else {
        bodyData.question = question;
      }

      const res = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(bodyData)
      });

      if (!res.ok) {
        throw new Error(`Error: ${res.status}`);
      }

      const data = await res.json();
      console.log(data);

      // searchMode => { final_answer, conversation_id, ...}
      // chatMode => { answer, conversation_id }
      if (data.conversation_id) {
        setSelectedConversation(data.conversation_id);
      }

      if (searchMode) {
        // user: "[검색요청] question"
        const userMsg: Message = {
          message_id: Date.now(),
          role: "user",
          content: `[검색요청] ${question}`,
          created_at: new Date().toISOString()
        };
        // assistant: data.final_answer
        const assistantMsg: Message = {
          message_id: Date.now() + 1,
          role: "assistant",
          content: data.final_answer,
          created_at: new Date().toISOString()
        };
        setMessages((prev) => [...prev, userMsg, assistantMsg]);

      } else {
        // normal chat
        const userMsg: Message = {
          message_id: Date.now(),
          role: "user",
          content: question,
          created_at: new Date().toISOString()
        };
        const assistantMsg: Message = {
          message_id: Date.now() + 1,
          role: "assistant",
          content: data.answer,
          created_at: new Date().toISOString()
        };
        setMessages((prev) => [...prev, userMsg, assistantMsg]);
      }

      setQuestion("");
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <Box sx={{ display: "flex", height: "100vh" }}>
      {/* 상단 바 */}
      <AppBar position="fixed">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Chat App
          </Typography>
          <Typography sx={{ mr: 2 }}>{userName}</Typography>
          <Button color="inherit" onClick={handleLogout}>
            Logout
          </Button>
        </Toolbar>
      </AppBar>

      {/* 왼쪽 Drawer (대화 목록 + "새 대화") */}
      <Drawer
        variant="permanent"
        sx={{
          width: 240,
          flexShrink: 0,
          [`& .MuiDrawer-paper`]: {
            width: 240,
            top: "64px",
            boxSizing: "border-box"
          }
        }}
      >
        <Toolbar />
        <Box sx={{ overflow: "auto" }}>
          <List>
            {/* 새로운 대화 시작 */}
            <ListItemButton
              onClick={handleNewConversation}
              sx={{ backgroundColor: "#f0f0f0" }}
            >
              <ListItemText primary="새로운 대화 시작" />
            </ListItemButton>
            <Divider />

            {conversations.map((c) => (
              <ListItemButton
                key={c.conversation_id}
                selected={c.conversation_id === selectedConversation}
                onClick={() => setSelectedConversation(c.conversation_id)}
              >
                <ListItemText
                  primary={c.title || `Conv ${c.conversation_id}`}
                />
              </ListItemButton>
            ))}
          </List>
        </Box>
      </Drawer>

      {/* 메인 영역 */}
      <Box sx={{ flexGrow: 1, marginTop: 8, p: 2 }}>
        {/* 메시지 목록 */}
        <Paper sx={{ mb: 2, height: "60vh", overflowY: "auto", p: 2 }}>
          {messages.length === 0 ? (
            <Box key={1} sx={{ mb: 1 }}>
              <Typography color="text.secondary">
                대화 내용이 없습니다.
              </Typography>
              <Divider sx={{ my: 1 }} />
            </Box>            
          ) : (
            messages.map((m) => (
              <Box key={m.message_id} sx={{ mb: 1 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  {m.role}:
                </Typography>
                <Typography>{m.content}</Typography>
                <Divider sx={{ my: 1 }} />
              </Box>
            ))
          )}
        </Paper>

        {/* 입력창 + 검색 토글 */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <FormControlLabel
            control={
              <Switch
                checked={searchMode}
                onChange={(e) => setSearchMode(e.target.checked)}
              />
            }
            label="정보검색"
          />

          <TextField
            fullWidth
            label="Ask something..."
            variant="outlined"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />

          <Button variant="contained" onClick={handleAsk}>
            Send
          </Button>
        </Box>
      </Box>
    </Box>
  );
}

export default ChatLayout;
