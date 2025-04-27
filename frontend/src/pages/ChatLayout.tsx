import { useEffect, useState, ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import dayjs from "dayjs";
import {
  Box, Drawer, Toolbar, List, ListItemButton, ListItemText, Divider,
  AppBar, Typography, Button, Paper, TextField, Switch, FormControlLabel,
  ListSubheader, Dialog, DialogTitle, DialogContent, DialogActions,
  LinearProgress
} from "@mui/material";
import { fetchWithAuth } from "../utils/api";

interface Message {
  message_id: number;
  role: string;
  content: string;
  created_at: string;
}
interface AgendaEvent {
  id: string;
  summary: string;
  start: { dateTime?: string; date?: string };
}

export default function ChatLayout() {
  const navigate = useNavigate();

  // ───────── 상태 ─────────
  const [userName, setUserName]           = useState("");
  const [conversations, setConversations] = useState<any[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<number|null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const [question,    setQuestion]    = useState("");
  const [searchMode,  setSearchMode]  = useState(false);
  const [uploadFile,  setUploadFile]  = useState<File|null>(null);
  const [isLoading,   setIsLoading]   = useState(false);

  const [agenda,      setAgenda]      = useState<AgendaEvent[]>([]);
  const [gcConnected, setGcConnected] = useState(false);

  // ─── 빠른 일정 Dialog ───
  const [openQuick,   setOpenQuick]   = useState(false);
  const [quickTitle,  setQuickTitle]  = useState("");
  const [quickDate,   setQuickDate]   = useState(dayjs().format("YYYY-MM-DD"));

  // ───────── 최초 로딩 ─────────
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { navigate("/login"); return; }

    // 사용자 정보
    fetchWithAuth("/auth/me").then(d => setUserName(d.username));

    // 대화 목록
    fetchWithAuth("/chat/conversations").then(setConversations);

    // 3일치 일정
    const end = new Date(Date.now() + 3*86400*1000).toISOString();
    fetchWithAuth(`/events?end=${end}`).then(setAgenda);

    // Google 연결 여부
    fetchWithAuth("/gcal/status").then(d => setGcConnected(d.connected));
  }, []);

  // ─── 대화 선택 → 메시지 불러오기 ───
  useEffect(() => {
    if (!selectedConversation) { setMessages([]); return; }
    fetchWithAuth(`/chat/conversations/${selectedConversation}`)
      .then(d => setMessages(d.messages));
  }, [selectedConversation]);

  // ─── Drawer Helper ───
  const reloadAgenda = async () => {
    const end = new Date(Date.now() + 3*86400*1000).toISOString();
    setAgenda(await fetchWithAuth(`/events?end=${end}`));
  };

  const refreshGcalStatus = async () => {
    const { connected } = await fetchWithAuth("/gcal/status");
    setGcConnected(connected);
  };

  // ───────── Google Calendar 연결 / 해제 ─────────
  const toggleGoogle = async () => {
    if (!gcConnected) {
      const { auth_url } = await fetchWithAuth("/gcal/authorize");
      const popup = window.open(auth_url, "_blank", "width=500,height=650");
      const handler = (e: MessageEvent) => {
        if (e.data === "gcal_success") {
          popup?.close();
          window.removeEventListener("message", handler);
          refreshGcalStatus();
          reloadAgenda();
        }
      };
      window.addEventListener("message", handler);
    } else {
      setGcConnected(false);
      setAgenda([]);
      
      await fetchWithAuth("/gcal/disconnect", { method: "DELETE" });
      refreshGcalStatus();      
    }
  };

  const quickSave = async () => {
    if (!quickTitle) return;           // 제목이 없으면 무시
    setIsLoading(true);
  
    const token = localStorage.getItem("token")!;
    const start = dayjs(quickDate).hour(9).minute(0).second(0);
    const end   = start.add(1, "hour");
  
    await fetch("http://localhost:8000/events", {
      method : "POST",
      headers: {
        "Content-Type" : "application/json",
        Authorization  : `Bearer ${token}`,
      },
      body: JSON.stringify({
        summary : quickTitle,
        start   : start.toISOString(),
        end     : end  .toISOString(),
        timezone: "Europe/Berlin",
      }),
    });
  
    // 새 일정이 저장됐으니 3‑일 미리보기 다시 읽기
    const until = new Date(Date.now() + 3*24*60*60*1000).toISOString();
    const mini  = await fetchWithAuth(`/events?end=${until}`);
    setAgenda(mini);
  
    setQuickTitle("");
    setOpenQuick(false);
    setIsLoading(false);
  };

  // ─── 새 대화 ───
  const newConversation = () => {
    setSelectedConversation(null);
    setMessages([]);
  };

  // ─── 채팅 / 검색 요청 ───
  const send = async () => {
    if (!question.trim()) return;

    setIsLoading(true);
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone; // ex. "Europe/Berlin"
    const endpoint = searchMode ? "/search" : "/chat";
    const payload: any = {
      conversation_id : selectedConversation,
      question        : question,
      timezone        : tz,
    };

    const data = await fetchWithAuth(endpoint, { method:"POST", body:JSON.stringify(payload)});
    if (data.conversation_id) setSelectedConversation(data.conversation_id);

    const now = Date.now();
    setMessages(p => [
      ...p,
      {message_id:now  , role:"user",      content: searchMode ? `[검색] ${question}` : question, created_at:new Date().toISOString()},
      {message_id:now+1, role:"assistant", content: searchMode ? data.final_answer   : data.answer, created_at:new Date().toISOString()}
    ]);

    // 일정이 실제로 바뀌었을 수도 있으니 다시 가져오기
    if (!searchMode && gcConnected) {
      reloadAgenda();         // ➜ Drawer 의 다가오는 일정 즉시 업데이트
    }
    setQuestion("");
    setIsLoading(false);
  };

  // ─── 파일 요약 ───
  const summarize = async () => {
    if (!uploadFile) return;
    setIsLoading(true);
    const fd = new FormData();
    fd.append("file", uploadFile);
    if (selectedConversation) fd.append("conversation_id", String(selectedConversation));
    const data = await fetchWithAuth("/summarize", { method:"POST", body:fd, raw:true });
    if (data.conversation_id) setSelectedConversation(data.conversation_id);

    const now = Date.now();
    setMessages(p => [
      ...p,
      {message_id:now,   role:"user",      content:`[파일요약] ${uploadFile.name}`, created_at:new Date().toISOString()},
      {message_id:now+1, role:"assistant", content:data.summary,                    created_at:new Date().toISOString()}
    ]);
    setUploadFile(null);
    setIsLoading(false);
  };

  // ───────── 렌더링 ─────────
  return (
    <Box sx={{ display:"flex", height:"100vh", overflow:"hidden" }}>
      {/* ─── Drawer ─── */}
      <Drawer variant="permanent" sx={{width:240,
        [`& .MuiDrawer-paper`]:{width:240, top:64, boxSizing:"border-box"}}}>
        <Toolbar />
        <List>
          <ListItemButton sx={{bgcolor:"#f5f5f5"}} onClick={newConversation}>
            <ListItemText primary="새로운 대화 시작"/>
          </ListItemButton>
          <Divider />
          {conversations.map(c=>(
            <ListItemButton key={c.conversation_id}
              selected={c.conversation_id===selectedConversation}
              onClick={()=>setSelectedConversation(c.conversation_id)}>
              <ListItemText primary={c.title||`Conv ${c.conversation_id}`} />
            </ListItemButton>
          ))}
        </List>
        <Divider />
        <List subheader={<ListSubheader>다가오는 일정</ListSubheader>}>
          {agenda.map(ev=>(
            <ListItemButton key={ev.id} onClick={()=>navigate(`/calendar?e=${ev.id}`)}>
              <ListItemText
                primary={ev.summary}
                secondary={dayjs(ev.start.dateTime||ev.start.date).format("DD HH:mm")}
              />
            </ListItemButton>
          ))}
          {agenda.length===0 && (
            <ListItemText sx={{p:2}} secondary="예정된 일정 없음"/>
          )}
        </List>
      </Drawer>

      {/* ─── Main ─── */}
      <Box sx={{ flex:1, display:"flex", flexDirection:"column", minWidth:0 }}>
        <AppBar position="relative" color="default" sx={{ zIndex:1200 }}>
          <Toolbar>
            <Typography sx={{ flexGrow:1 }}>대화</Typography>
            <Button variant="outlined" onClick={toggleGoogle} sx={{mr:2}}>
              {gcConnected ? "Google 연결 해제" : "Google 연결"}
            </Button>
            <Typography sx={{mr:2}}>{userName}</Typography>
            <Button onClick={()=>{localStorage.removeItem("token");navigate("/login");}}>
              Logout
            </Button>
          </Toolbar>
        </AppBar>

        {isLoading && <LinearProgress />}

        <Paper sx={{ height: '60vh', m:2, p:2, overflowY:"auto" }}>
          {messages.length===0
            ? <Typography color="text.secondary">대화가 없습니다.</Typography>
            : messages.map(m=>(
                <Box key={m.message_id} sx={{mb:1}}>
                  <Typography variant="subtitle2" color="text.secondary">{m.role}:</Typography>
                  <Typography whiteSpace="pre-line">{m.content}</Typography>
                  <Divider sx={{my:1}}/>
                </Box>
              ))}
        </Paper>

        {/* 입력 */}
        <Box sx={{m:2, display:"flex", gap:1}}>
          <FormControlLabel control={
            <Switch checked={searchMode} onChange={e=>setSearchMode(e.target.checked)}/>
          } label="정보검색"/>
          <TextField fullWidth label="메시지 입력" value={question}
            onChange={e=>setQuestion(e.target.value)}
            onKeyDown={e=>{if(e.key==="Enter") send();}}/>
          <Button variant="contained" onClick={send} disabled={isLoading}>Send</Button>
        </Box>

        {/* 파일 & 빠른 일정 */}
        <Box sx={{m:2, display:"flex", gap:1}}>
          <Button variant="outlined" component="label" disabled={isLoading}>
            파일 선택
            <input hidden type="file" accept=".pdf,.txt" onChange={(e:ChangeEvent<HTMLInputElement>)=>{
              setUploadFile(e.target.files?.[0]||null);
            }}/>
          </Button>
          <Typography variant="body2" sx={{flex:1}}>
            {uploadFile ? uploadFile.name : "선택된 파일 없음"}
          </Typography>
          <Button variant="contained" disabled={!uploadFile||isLoading} onClick={summarize}>
            문서 요약
          </Button>
          <Button variant="outlined" onClick={()=>setOpenQuick(true)}>빠른 일정</Button>
        </Box>
      </Box>

      {/* 빠른 일정 Dialog */}
      <Dialog open={openQuick} onClose={()=>setOpenQuick(false)}>
        <DialogTitle>빠른 일정 추가</DialogTitle>
        <DialogContent sx={{display:"flex",flexDirection:"column",gap:2,mt:1}}>
          <TextField label="제목" value={quickTitle}
            onChange={e=>setQuickTitle(e.target.value)}/>
          <TextField type="date" label="날짜" InputLabelProps={{shrink:true}}
            value={quickDate} onChange={e=>setQuickDate(e.target.value)}/>
        </DialogContent>
        <DialogActions>
          <Button onClick={()=>setOpenQuick(false)}>취소</Button>
          <Button onClick={quickSave} disabled={!quickTitle}>
            저장
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
