/**
 * Simple line-by-line diff algorithm
 * Returns an array of diff lines marking additions, deletions, and context
 */

export type DiffLine = {
  type: 'context' | 'addition' | 'deletion'
  content: string
  lineNum?: number
}

export function computeLineDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  
  const result: DiffLine[] = []
  
  // Simple diff: use longest common subsequence concept (simplified)
  const oldSet = new Map<string, number[]>()
  const newSet = new Map<string, number[]>()
  
  // Build line maps
  oldLines.forEach((line, i) => {
    if (!oldSet.has(line)) oldSet.set(line, [])
    oldSet.get(line)!.push(i)
  })
  
  newLines.forEach((line, i) => {
    if (!newSet.has(line)) newSet.set(line, [])
    newSet.get(line)!.push(i)
  })
  
  // Track matched lines
  const matchedOld = new Set<number>()
  const matchedNew = new Set<number>()
  
  // Find matching lines (greedy approach for simplicity)
  oldLines.forEach((oldLine, oldIdx) => {
    if (matchedOld.has(oldIdx)) return
    
    const potentialMatches = newSet.get(oldLine) || []
    for (const newIdx of potentialMatches) {
      if (!matchedNew.has(newIdx)) {
        matchedOld.add(oldIdx)
        matchedNew.add(newIdx)
        break
      }
    }
  })
  
  // Generate diff
  let oldIdx = 0
  let newIdx = 0
  
  while (oldIdx < oldLines.length || newIdx < newLines.length) {
    if (oldIdx < oldLines.length && matchedOld.has(oldIdx) && newIdx < newLines.length && matchedNew.has(newIdx)) {
      // Context line
      if (oldLines[oldIdx] === newLines[newIdx]) {
        result.push({
          type: 'context',
          content: oldLines[oldIdx],
          lineNum: oldIdx + 1,
        })
        oldIdx++
        newIdx++
      } else {
        // Moved to different position, treat as delete + add
        result.push({
          type: 'deletion',
          content: oldLines[oldIdx],
          lineNum: oldIdx + 1,
        })
        oldIdx++
      }
    } else if (oldIdx < oldLines.length && !matchedOld.has(oldIdx)) {
      // Deletion
      result.push({
        type: 'deletion',
        content: oldLines[oldIdx],
        lineNum: oldIdx + 1,
      })
      oldIdx++
    } else if (newIdx < newLines.length && !matchedNew.has(newIdx)) {
      // Addition
      result.push({
        type: 'addition',
        content: newLines[newIdx],
        lineNum: newIdx + 1,
      })
      newIdx++
    } else {
      oldIdx++
      newIdx++
    }
  }
  
  return result
}

/**
 * Format unified diff output like `diff` or `git diff`
 */
export function formatUnifiedDiff(
  leftLabel: string,
  rightLabel: string,
  oldText: string,
  newText: string
): string[] {
  const lines: string[] = []
  const diff = computeLineDiff(oldText, newText)
  
  lines.push(`--- a/${leftLabel}`)
  lines.push(`+++ b/${rightLabel}`)
  
  let context = 0
  const contextWindow: DiffLine[] = []
  
  for (const diffLine of diff) {
    if (diffLine.type === 'context') {
      contextWindow.push(diffLine)
      if (contextWindow.length > 3) {
        contextWindow.shift()
      }
    } else {
      // Output any context before change
      for (const ctx of contextWindow) {
        lines.push(` ${ctx.content}`)
      }
      contextWindow.length = 0
      
      // Output the change
      if (diffLine.type === 'deletion') {
        lines.push(`-${diffLine.content}`)
      } else {
        lines.push(`+${diffLine.content}`)
      }
    }
  }
  
  return lines
}
