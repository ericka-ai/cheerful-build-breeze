import { createFileRoute } from "@tanstack/react-router";
import { useState, useRef, useEffect, useCallback } from "react";
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
  Loader2,
} from "lucide-react";

export const Route = createFileRoute("/devin")({
  component: DevinPage,
});

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

interface FileEntry {
  name: string;
  type: "folder" | "file";
  content?: string;
  children?: FileEntry[];
}

interface TerminalLine {
  text: string;
  type: "command" | "output" | "error" | "info";
}

const DEEPSEEK_URL = "https://api.deepseek.com/chat/completions";
const DEEPSEEK_KEY = "sk-86a63bdb36304c88b7c268c1eb2ef393";
const DEFAULT_MODEL = "deepseek-chat";

const SYSTEM_PROMPT = `You are OpenDevin, an AI software engineer assistant. You help users by writing code, explaining concepts, and solving programming problems.

When the user asks you to write code or create something, respond with:
1. A brief explanation of what you'll do
2. The code in a fenced code block with the filename as a comment on the first line, e.g.:
\`\`\`python
# filename: main.py
print("hello world")
\`\`\`

You can create multiple files by using multiple code blocks. Always include the filename comment.
Keep responses concise and focused on code. You are a coding assistant, not a general chatbot.`;

async function callLLM(messages: Message[], model: string): Promise<string> {
  const response = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${DEEPSEEK_KEY}`,
    },
    body: JSON.stringify({
      model,
      messages,
      temperature: 0.3,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API error ${response.status}: ${errorText}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content ?? "No response received.";
}

function extractCodeBlocks(
  text: string,
): Array<{ filename: string; language: string; code: string }> {
  const blocks: Array<{ filename: string; language: string; code: string }> = [];
  const regex = /```(\w+)?\n([\s\S]*?)```/g;
  let match;

  while ((match = regex.exec(text)) !== null) {
    const language = match[1] || "text";
    const code = match[2].trim();

    let filename = `file.${language === "python" ? "py" : language === "javascript" ? "js" : language === "typescript" ? "ts" : language === "html" ? "html" : language === "css" ? "css" : language === "bash" || language === "sh" ? "sh" : language}`;

    const filenameMatch = code.match(/^#\s*filename:\s*(.+)/m);
    if (filenameMatch) {
      filename = filenameMatch[1].trim();
    }

    blocks.push({ filename, language, code });
  }

  return blocks;
}

function FileTree({
  files,
  depth = 0,
  onFileClick,
}: {
  files: FileEntry[];
  depth?: number;
  onFileClick?: (file: FileEntry) => void;
}) {
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
              } else {
                onFileClick?.(file);
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
            <FileTree files={file.children!} depth={depth + 1} onFileClick={onFileClick} />
          )}
        </div>
      ))}
    </div>
  );
}

function ChatPanel({
  onCodeGenerated,
  onTerminalLog,
  model,
}: {
  onCodeGenerated: (files: Array<{ filename: string; language: string; code: string }>) => void;
  onTerminalLog: (lines: TerminalLine[]) => void;
  model: string;
}) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        'Hi! I\'m OpenDevin, an AI Software Engineer. What would you like to build with me today?\n\nTry asking me to write some code, like:\n- "Create a Python script that generates random passwords"\n- "Write a React component for a todo list"\n- "Build a simple REST API in Node.js"',
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(async () => {
    if (!input.trim() || isLoading) return;
    const userMsg: Message = { role: "user", content: input };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setIsLoading(true);

    onTerminalLog([
      {
        text: `$ opendevin process "${input.slice(0, 50)}${input.length > 50 ? "..." : ""}"`,
        type: "command",
      },
      { text: "Thinking...", type: "info" },
    ]);

    try {
      const apiMessages: Message[] = [
        { role: "system", content: SYSTEM_PROMPT },
        ...newMessages.filter((m) => m.role !== "system"),
      ];

      const reply = await callLLM(apiMessages, model);
      const assistantMsg: Message = { role: "assistant", content: reply };
      setMessages((prev) => [...prev, assistantMsg]);

      const codeBlocks = extractCodeBlocks(reply);
      if (codeBlocks.length > 0) {
        onCodeGenerated(codeBlocks);
        onTerminalLog([
          {
            text: `$ opendevin process "${input.slice(0, 50)}${input.length > 50 ? "..." : ""}"`,
            type: "command",
          },
          {
            text: `✓ Generated ${codeBlocks.length} file(s): ${codeBlocks.map((b) => b.filename).join(", ")}`,
            type: "output",
          },
          { text: "Files written to workspace/", type: "info" },
        ]);
      } else {
        onTerminalLog([
          {
            text: `$ opendevin process "${input.slice(0, 50)}${input.length > 50 ? "..." : ""}"`,
            type: "command",
          },
          { text: "✓ Response ready", type: "output" },
        ]);
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "Unknown error";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Error communicating with the AI model: ${errorMsg}\n\nThe free API might be rate-limited. Try again in a moment.`,
        },
      ]);
      onTerminalLog([
        { text: `$ opendevin process "${input.slice(0, 50)}..."`, type: "command" },
        { text: `✗ Error: ${errorMsg}`, type: "error" },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, messages, model, onCodeGenerated, onTerminalLog]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-neutral-700 bg-neutral-800/80">
        <span className="text-sm font-medium text-neutral-200">💬 Chat</span>
        {isLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />}
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages
          .filter((m) => m.role !== "system")
          .map((msg, i) => (
            <div
              key={i}
              className={`max-w-[90%] rounded-lg px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === "assistant"
                  ? "bg-neutral-700 text-neutral-100"
                  : "bg-blue-600 text-white ml-auto"
              }`}
            >
              {msg.content}
            </div>
          ))}
        {isLoading && (
          <div className="max-w-[90%] rounded-lg px-4 py-2.5 text-sm bg-neutral-700 text-neutral-400">
            <span className="inline-flex items-center gap-1">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Thinking...
            </span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="p-3 border-t border-neutral-700">
        <div className="flex items-center gap-2 bg-neutral-800 rounded-lg border border-neutral-600 px-3 py-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={isLoading ? "Waiting for response..." : "Send a message..."}
            disabled={isLoading}
            className="flex-1 bg-transparent text-sm text-neutral-200 placeholder:text-neutral-500 outline-none disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="text-neutral-400 hover:text-blue-400 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function CodeEditorPanel({
  files,
  activeFile,
  onFileClick,
}: {
  files: FileEntry[];
  activeFile: FileEntry | null;
  onFileClick: (file: FileEntry) => void;
}) {
  const codeLines = (
    activeFile?.content || "# Welcome to OpenDevin!\n# Ask me to write some code."
  ).split("\n");

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
            <FileTree files={files} onFileClick={onFileClick} />
          </div>
          <div className="flex-1 flex flex-col min-w-0">
            <div className="flex items-center px-3 py-1.5 bg-neutral-800 border-b border-neutral-700">
              <span className="text-xs text-neutral-300 bg-neutral-700 px-3 py-1 rounded">
                {activeFile?.name || "welcome"}
              </span>
            </div>
            <div className="flex-1 p-4 font-mono text-sm bg-neutral-900 overflow-auto">
              {codeLines.map((line, i) => (
                <div key={i} className="flex">
                  <span className="text-neutral-600 select-none w-8 text-right mr-4 shrink-0">
                    {i + 1}
                  </span>
                  <span className="text-neutral-200 whitespace-pre">{line}</span>
                </div>
              ))}
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

function TerminalPanel({ lines }: { lines: TerminalLine[] }) {
  const termRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (termRef.current) {
      termRef.current.scrollTop = termRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-neutral-700 bg-neutral-800/80">
        <TerminalIcon className="h-4 w-4 text-neutral-400" />
        <span className="text-sm font-medium text-neutral-200">Terminal</span>
      </div>
      <div ref={termRef} className="flex-1 p-3 font-mono text-sm bg-neutral-900 overflow-auto">
        {lines.map((line, i) => (
          <div
            key={i}
            className={
              line.type === "command"
                ? "text-green-400"
                : line.type === "error"
                  ? "text-red-400"
                  : line.type === "info"
                    ? "text-yellow-400"
                    : "text-neutral-300"
            }
          >
            {line.text}
          </div>
        ))}
        <div className="text-green-400">
          {"$ "}
          <span className="inline-block w-2 h-4 bg-green-400 animate-pulse ml-0.5 align-middle" />
        </div>
      </div>
    </div>
  );
}

function SettingsModal({
  isOpen,
  onClose,
  model,
  onSave,
}: {
  isOpen: boolean;
  onClose: () => void;
  model: string;
  onSave: (model: string) => void;
}) {
  const [localModel, setLocalModel] = useState(model);

  useEffect(() => {
    setLocalModel(model);
  }, [model, isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-neutral-800 border border-neutral-700 rounded-xl w-full max-w-md p-6 shadow-2xl">
        <h2 className="text-lg font-semibold text-neutral-100 mb-4">Settings</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-neutral-400 mb-1">LLM Model</label>
            <select
              value={localModel}
              onChange={(e) => setLocalModel(e.target.value)}
              className="w-full bg-neutral-900 border border-neutral-600 rounded-lg px-3 py-2 text-sm text-neutral-200 outline-none focus:border-blue-500"
            >
              <option value="deepseek-chat">DeepSeek Chat (default)</option>
              <option value="deepseek-coder">DeepSeek Coder</option>
              <option value="deepseek-reasoner">DeepSeek Reasoner</option>
            </select>
            <p className="text-xs text-neutral-500 mt-1">Powered by DeepSeek AI</p>
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
            onClick={() => {
              onSave(localModel);
              onClose();
            }}
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
  const [model, setModel] = useState(DEFAULT_MODEL);

  const [workspaceFiles, setWorkspaceFiles] = useState<FileEntry[]>([
    {
      name: "workspace",
      type: "folder",
      children: [],
    },
  ]);
  const [activeFile, setActiveFile] = useState<FileEntry | null>(null);
  const [terminalLines, setTerminalLines] = useState<TerminalLine[]>([
    { text: "OpenDevin Terminal v0.1.0", type: "info" },
    { text: "Ready. Waiting for commands...", type: "info" },
  ]);

  const handleCodeGenerated = useCallback(
    (codeBlocks: Array<{ filename: string; language: string; code: string }>) => {
      const newFiles: FileEntry[] = codeBlocks.map((block) => ({
        name: block.filename,
        type: "file" as const,
        content: block.code,
      }));

      setWorkspaceFiles((prev) => {
        const workspace = { ...prev[0] };
        const existingChildren = workspace.children || [];
        const updatedChildren = [...existingChildren];

        for (const newFile of newFiles) {
          const existingIdx = updatedChildren.findIndex((f) => f.name === newFile.name);
          if (existingIdx >= 0) {
            updatedChildren[existingIdx] = newFile;
          } else {
            updatedChildren.push(newFile);
          }
        }

        workspace.children = updatedChildren;
        return [workspace];
      });

      if (newFiles.length > 0) {
        setActiveFile(newFiles[0]);
      }
    },
    [],
  );

  const handleTerminalLog = useCallback((lines: TerminalLine[]) => {
    setTerminalLines((prev) => [...prev, ...lines]);
  }, []);

  const handleFileClick = useCallback((file: FileEntry) => {
    if (file.type === "file") {
      setActiveFile(file);
    }
  }, []);

  return (
    <div className="h-screen w-screen flex bg-neutral-900 text-white">
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

      <div className="flex-1 p-2 min-w-0">
        <ResizablePanelGroup orientation="vertical">
          <ResizablePanel defaultSize={65} minSize={30}>
            <ResizablePanelGroup orientation="horizontal">
              <ResizablePanel defaultSize={35} minSize={25}>
                <div className="h-full rounded-xl overflow-hidden border border-neutral-700 bg-neutral-800">
                  <ChatPanel
                    onCodeGenerated={handleCodeGenerated}
                    onTerminalLog={handleTerminalLog}
                    model={model}
                  />
                </div>
              </ResizablePanel>
              <ResizableHandle className="mx-1 bg-transparent hover:bg-blue-500/30 transition-colors" />
              <ResizablePanel defaultSize={65} minSize={30}>
                <div className="h-full rounded-xl overflow-hidden border border-neutral-700 bg-neutral-800">
                  <CodeEditorPanel
                    files={workspaceFiles}
                    activeFile={activeFile}
                    onFileClick={handleFileClick}
                  />
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
          <ResizableHandle className="my-1 bg-transparent hover:bg-blue-500/30 transition-colors" />
          <ResizablePanel defaultSize={35} minSize={15}>
            <div className="h-full rounded-xl overflow-hidden border border-neutral-700 bg-neutral-800">
              <TerminalPanel lines={terminalLines} />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        model={model}
        onSave={(m) => {
          setModel(m);
        }}
      />
    </div>
  );
}
