#!/usr/bin/env ruby
# Structural checks only; API recipes need their own compilation/behavior checks.
require "pathname"
require "uri"
require "yaml"

root = Pathname.new(__dir__).parent
files = [root.join("README.md"), root.join("AGENTS.md")]
files += root.glob("{skills,validation}/**/*.md").reject { |path| path.to_s.include?("/target/") }
errors = []
links = 0

files.each do |path|
  relative = path.relative_path_from(root)
  text = path.read
  if path.basename.to_s == "SKILL.md"
    frontmatter = text.match(/\A---\r?\n(.*?)\r?\n---(?:\r?\n|\z)/m)
    begin
      raise "missing YAML frontmatter" unless frontmatter
      data = YAML.safe_load(frontmatter[1])
      raise "frontmatter must be a mapping" unless data.is_a?(Hash)
      %w[name description].each do |key|
        raise "#{key} must be a nonempty string" unless data[key].is_a?(String) && !data[key].strip.empty?
      end
      raise "name must match directory" unless data["name"] == path.parent.basename.to_s
    rescue StandardError => error
      errors << "#{relative}: #{error.message}"
    end
  end

  fence = nil
  prose = []
  text.each_line.with_index(1) do |line, number|
    if fence
      fence = nil if line.match?(/^ {0,3}#{Regexp.escape(fence[0])}{#{fence[1]},}\s*$/)
      next
    end
    opening = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/)
    if opening
      fence = [opening[1][0], opening[1].length, number]
    else
      prose << [number, line]
    end
  end
  errors << "#{relative}:#{fence[2]}: unclosed code fence" if fence

  prose.each do |number, line|
    line.scan(/\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)/) do |capture|
      target = capture[0].sub(/\A</, "").sub(/>\z/, "")
      next if target.start_with?("#", "//") || target.match?(/\A[a-z][a-z0-9+.-]*:/i)
      filename = URI::DEFAULT_PARSER.unescape(target.split(/[?#]/, 2)[0])
      next if filename.empty?
      links += 1
      errors << "#{relative}:#{number}: missing local target #{target}" unless path.parent.join(filename).exist?
    end
  end
end

unless errors.empty?
  warn errors.join("\n")
  exit 1
end
puts "Checked #{files.length} Markdown files: skill frontmatter, fences, and #{links} local file links."
