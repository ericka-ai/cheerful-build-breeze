import { createFileRoute } from "@tanstack/react-router";
import { useState, useRef, useEffect } from "react";
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "@/components/ui/resizable";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Settings,
  Send,
  FolderOpen,
  FileText,
  ChevronRight,
  ChevronDown,
  Terminal as TerminalIcon,
  Code,
  Globe,
  RefreshCw,
} from "lucide-react";

export const Route = createFileRoute("/devin")({
  component: DevinPage,
});

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface FileEntry {
  name: string;
  type: "folder" | "file";
  children?: FileEntry[];
}

const SAMPLE_FILES: FileEntry[] = [
  {
    name: "workspace",
    type: "folder",
    children: [
      { name: "main.py", type: "file" },
      { name: "utils.py", type: "file" },
      { name: "README.md", type: "file" },
    ],
  },
];

function FileTree({ files, depth = 0 }: { files: FileEntry[]; depth?: number }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ workspace: true });

  return (
    <div>
      {files.map((file) => (
        <div key={file.name}>
          <div
            className="flex items-center gap-1 px-2 py-1 hover:bg-neutral-700/50 cursor-pointer text-sm text-neutral-300"
            style={{ paddingLeft: `${depth * 16 + 8}px` }}
            onClick={() => {
              if (file.type === "folder") {
                setExpanded((prev) => ({ ...prev, [file.name]: !prev[file.name] }));
              }
            }}
          >
            {file.type === "folder" ? (
              expanded[file.name] ? (
                <ChevronDown className="h-3.5 w-3.5 shrink-0" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0" />
              )
            ) : (
              <span className="w-3.5" />
            )}
            {file.type === "folder" ? (
              <FolderOpen className="h-4 w-4 shrink-0 text-yellow-500" />
            ) : (
              <FileText className="h-4 w-4 shrink-0 text-blue-400" />
            )}
            <span className="truncate">{file.name}</span>
          </div>
          {file.type === "folder" && expanded[file.name] && file.children && (
            <FileTree files={file.children!} depth={depth + 1} />
          )}
        </div>
      ))}
    </div>
  );
}

function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hi! I'm OpenDevin, an AI Software Engineer. What would you like to build with me today?",
    },
  ]);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    const userMsg: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "I'll help you with that. Let me analyze the requirements and start working on it...",
        },
      ]);
    }, 1000);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-neutral-700 bg-neutral-800/80">
        <span className="text-sm font-medium text-neutral-200">💬 Chat</span>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-lg px-4 py-2.5 text-sm leading-relaxed ${
              msg.role === "assistant"
                ? "bg-neutral-700 text-neutral-100"
                : "bg-blue-600 text-white ml-auto"
            }`}
          >
            {msg.content}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="p-3 border-t border-neutral-700">
        <div className="flex items-center gap-2 bg-neutral-800 rounded-lg border border-neutral-600 px-3 py-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Send a message (won't interrupt the Assistant)"
            className="flex-1 bg-transparent text-sm text-neutral-200 placeholder:text-neutral-500 outline-none"
          />
          <button
            onClick={handleSend}
            className="text-neutral-400 hover:text-blue-400 transition-colors"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function CodeEditorPanel() {
  const welcomeCode = "# Welcome to OpenDevin!";

  return (
    <div className="flex flex-col h-full">
      <Tabs defaultValue="editor" className="flex flex-col h-full">
        <div className="flex items-center border-b border-neutral-700 bg-neutral-800/80">
          <TabsList className="bg-transparent h-auto p-0 rounded-none">
            <TabsTrigger
              value="editor"
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-2 text-sm text-neutral-400 data-[state=active]:text-neutral-200"
            >
              <Code className="h-4 w-4 mr-1.5" />
              Code Editor
            </TabsTrigger>
            <TabsTrigger
              value="browser"
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-2 text-sm text-neutral-400 data-[state=active]:text-neutral-200"
            >
              <Globe className="h-4 w-4 mr-1.5" />
              Browser
            </TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="editor" className="flex-1 flex mt-0 min-h-0">
          <div className="w-48 border-r border-neutral-700 bg-neutral-850 overflow-y-auto shrink-0">
            <div className="flex items-center gap-1 px-3 py-2 text-xs text-neutral-400 uppercase tracking-wider">
              <FolderOpen className="h-3.5 w-3.5" />
              <span>workspace</span>
              <RefreshCw className="h-3 w-3 ml-auto cursor-pointer hover:text-neutral-200" />
            </div>
            <FileTree files={SAMPLE_FILES} />
          </div>
          <div className="flex-1 flex flex-col min-w-0">
            <div className="flex items-center px-3 py-1.5 bg-neutral-800 border-b border-neutral-700">
              <span className="text-xs text-neutral-300 bg-neutral-700 px-3 py-1 rounded">
                welcome
              </span>
            </div>
            <div className="flex-1 p-4 font-mono text-sm bg-neutral-900 overflow-auto">
              <div className="flex">
                <span className="text-neutral-600 select-none w-8 text-right mr-4">1</span>
                <span className="text-yellow-300">{welcomeCode}</span>
              </div>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="browser" className="flex-1 mt-0 min-h-0">
          <div className="flex items-center justify-center h-full text-neutral-500 text-sm">
            <div className="text-center">
              <Globe className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>Browser preview will appear here</p>
              <p className="text-xs text-neutral-600 mt-1">
                The agent can browse the web to research and test
              </p>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function TerminalPanel() {
  const [history] = useState(["$ "]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-neutral-700 bg-neutral-800/80">
        <TerminalIcon className="h-4 w-4 text-neutral-400" />
        <span className="text-sm font-medium text-neutral-200">Terminal</span>
      </div>
      <div className="flex-1 p-3 font-mono text-sm bg-neutral-900 overflow-auto">
        {history.map((line, i) => (
          <div key={i} className="text-green-400">
            {line}
            {i === history.length - 1 && (
              <span className="inline-block w-2 h-4 bg-green-400 animate-pulse ml-0.5 align-middle" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SettingsModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-neutral-800 border border-neutral-700 rounded-xl w-full max-w-md p-6 shadow-2xl">
        <h2 className="text-lg font-semibold text-neutral-100 mb-4">Settings</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-neutral-400 mb-1">LLM Model</label>
            <select className="w-full bg-neutral-900 border border-neutral-600 rounded-lg px-3 py-2 text-sm text-neutral-200 outline-none focus:border-blue-500">
              <option>gpt-4</option>
              <option>gpt-3.5-turbo</option>
              <option>claude-3-opus</option>
              <option>claude-3-sonnet</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-neutral-400 mb-1">API Key</label>
            <input
              type="password"
              placeholder="sk-..."
              className="w-full bg-neutral-900 border border-neutral-600 rounded-lg px-3 py-2 text-sm text-neutral-200 outline-none focus:border-blue-500 placeholder:text-neutral-600"
            />
          </div>
          <div>
            <label className="block text-sm text-neutral-400 mb-1">Agent</label>
            <select className="w-full bg-neutral-900 border border-neutral-600 rounded-lg px-3 py-2 text-sm text-neutral-200 outline-none focus:border-blue-500">
              <option>MonologueAgent</option>
              <option>CodeActAgent</option>
              <option>PlannerAgent</option>
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-neutral-600 text-neutral-300 hover:bg-neutral-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

function DevinPage() {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="h-screen w-screen flex bg-neutral-900 text-white">
      {/* Left sidebar */}
      <div className="flex flex-col h-full w-14 items-center py-4 bg-neutral-900 border-r border-neutral-800 shrink-0">
        <div className="flex-1" />
        <button
          onClick={() => setSettingsOpen(true)}
          className="p-2 rounded-lg hover:bg-neutral-800 text-neutral-400 hover:text-neutral-200 transition-colors"
          title="Settings"
        >
          <Settings className="h-5 w-5" />
        </button>
      </div>

      {/* Main content */}
      <div className="flex-1 p-2 min-w-0">
        <ResizablePanelGroup orientation="vertical">
          <ResizablePanel defaultSize={65} minSize={30}>
            <ResizablePanelGroup orientation="horizontal">
              <ResizablePanel defaultSize={35} minSize={25}>
                <div className="h-full rounded-xl overflow-hidden border border-neutral-700 bg-neutral-800">
                  <ChatPanel />
                </div>
              </ResizablePanel>
              <ResizableHandle className="mx-1 bg-transparent hover:bg-blue-500/30 transition-colors" />
              <ResizablePanel defaultSize={65} minSize={30}>
                <div className="h-full rounded-xl overflow-hidden border border-neutral-700 bg-neutral-800">
                  <CodeEditorPanel />
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
          <ResizableHandle className="my-1 bg-transparent hover:bg-blue-500/30 transition-colors" />
          <ResizablePanel defaultSize={35} minSize={15}>
            <div className="h-full rounded-xl overflow-hidden border border-neutral-700 bg-neutral-800">
              <TerminalPanel />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      <SettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
