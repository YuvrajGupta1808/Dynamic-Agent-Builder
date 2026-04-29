import { ChevronRight, FileCode2, Folder, FolderOpen } from "lucide-react";

import type { FileTreeNode } from "../types/api";
import { cn } from "../lib/utils";

interface FileTreeProps {
  node?: FileTreeNode | null;
  selectedPath?: string;
  onSelect: (path: string) => void;
}

export function FileTree({ node, selectedPath, onSelect }: FileTreeProps) {
  if (!node) return <div className="empty-state">No workspace loaded</div>;
  return (
    <div className="file-tree">
      {node.children.map((child) => (
        <TreeNode key={child.path || child.name} node={child} selectedPath={selectedPath} onSelect={onSelect} depth={0} />
      ))}
    </div>
  );
}

function TreeNode({
  node,
  selectedPath,
  onSelect,
  depth,
}: {
  node: FileTreeNode;
  selectedPath?: string;
  onSelect: (path: string) => void;
  depth: number;
}) {
  const isDirectory = node.type === "directory";
  const isSelected = selectedPath === node.path;
  return (
    <div>
      <button
        type="button"
        className={cn("tree-row", isSelected && "selected")}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={() => {
          if (!isDirectory) onSelect(node.path);
        }}
      >
        {isDirectory ? <ChevronRight className="tree-chevron" /> : <span className="tree-spacer" />}
        {isDirectory ? (
          depth === 0 ? (
            <FolderOpen className="tree-icon" />
          ) : (
            <Folder className="tree-icon" />
          )
        ) : (
          <FileCode2 className="tree-icon" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isDirectory &&
        node.children.map((child) => (
          <TreeNode key={child.path || child.name} node={child} selectedPath={selectedPath} onSelect={onSelect} depth={depth + 1} />
        ))}
    </div>
  );
}

