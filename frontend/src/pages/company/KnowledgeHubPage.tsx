import { Link } from 'react-router'

import { CalculatorIcon, ClipboardIcon, CompareIcon, PuzzleIcon, SparkIcon } from '@/components/icons'
import { InfoPage } from '@/features/company/InfoPage'

const GUIDES = [
  ['boards', 'Plywood, MDF or HDHMR?'],
  ['adhesives', 'Using wood adhesives'],
  ['hinges', 'Choosing cabinet hinges'],
  ['channels', 'Drawer channels'],
  ['locks', 'Door locks'],
  ['glass', 'Glass door fittings'],
  ['tools', 'Drill bits and power tools'],
  ['safety', 'Working safely'],
] as const

const TOOLS = [
  ['Quantity calculator', 'Work out how much you need for a job.', '/quantity', CalculatorIcon],
  ['Project builder', 'Get a list of parts for a project.', '/projects', ClipboardIcon],
  ['Compare products', 'See specifications side by side.', '/compare', CompareIcon],
  ['AI assistant', 'Ask which product suits your job.', '/ai-assistant', SparkIcon],
  ['Compatibility checks', 'Product pages and the cart check which parts work together.', '/products', PuzzleIcon],
] as const

/** /knowledge-hub — general selection advice (no brand-specific claims) and the shop's planning tools. */
export function KnowledgeHubPage() {
  return (
    <InfoPage
      group="company"
      title="Knowledge Hub"
      intro="Practical guides for choosing boards, fittings, locks and tools, and the planning tools on our site."
      note="These guides are general advice. Always follow the manufacturer’s instructions and the specifications on each product page."
    >
      <nav aria-label="Guides" className="rounded-xl bg-steel-50 p-4 ring-1 ring-steel-200">
        <p className="text-sm font-semibold text-ink-950">In this hub</p>
        <ul className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {GUIDES.map(([id, label]) => (
            <li key={id}>
              <a href={`#${id}`} className="text-ink-800 underline-offset-2 hover:text-amber-700 hover:underline">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <h2>Planning tools</h2>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {TOOLS.map(([title, text, to, Icon]) => (
          <li key={title}>
            <Link to={to} className="card card-hover flex h-full gap-3 p-4">
              <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-lg bg-ink-950 text-amber-400">
                <Icon className="size-5" />
              </span>
              <span>
                <span className="block font-semibold text-ink-950">{title}</span>
                <span className="block text-sm text-ink-600">{text}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <h2 id="boards">Plywood, MDF or HDHMR?</h2>
      <ul>
        <li>
          <strong>Plywood</strong> is made of cross-laid wood layers. It holds screws well and is the usual choice for
          carcasses, shutters and furniture that carries load. Moisture-resistant (MR) grades suit dry indoor areas; for
          kitchens, bathrooms and other damp places choose a boiling-water-resistant grade (often sold as BWR or BWP).
        </li>
        <li>
          <strong>MDF</strong> has a smooth, even surface that is easy to paint and shape, which suits shutters, panels and
          decorative work. Keep it away from water and avoid it where screws must carry heavy loads.
        </li>
        <li>
          <strong>HDHMR</strong> is a denser board with better moisture resistance than MDF. It is often used for kitchen and
          wardrobe shutters.
        </li>
        <li>
          <strong>Thickness:</strong> carcasses and shelves commonly use 16–19 mm boards, and back panels thinner sheets. Long
          shelves need extra support or a thicker board.
        </li>
      </ul>
      <p>
        Browse <Link to="/c/plywood-mdf-hdhmr">Plywood, MDF &amp; HDHMR</Link>.
      </p>

      <h2 id="adhesives">Using wood adhesives</h2>
      <ul>
        <li>Pick the adhesive for the job on its pack: wood to wood, laminate to board, or heat- or water-resistant work.</li>
        <li>Surfaces should be clean, dry and dust-free. Spread an even layer and clamp or press the joint.</li>
        <li>Follow the drying and pressing times on the pack before loading the joint.</li>
      </ul>
      <p>
        Browse <Link to="/c/fevicol">Fevicol</Link>.
      </p>

      <h2 id="hinges">Choosing cabinet hinges</h2>
      <ul>
        <li>
          <strong>Overlay:</strong> full overlay when the door covers the side panel, half overlay when two doors share one
          side panel, and inset when the door sits inside the frame. The hinge type must match.
        </li>
        <li>
          <strong>Soft-close</strong> hinges close the door gently; the standard type needs a door buffer or catch to close
          quietly.
        </li>
        <li>
          <strong>How many:</strong> taller and heavier doors need more hinges. Use the manufacturer’s chart for the door’s
          height, width and weight.
        </li>
        <li>
          Check the cup size and the door thickness the hinge supports; both are listed in the product specifications.
        </li>
      </ul>
      <p>
        Browse <Link to="/c/hinges-channels-handles">Hinges, Channels &amp; Handles</Link>.
      </p>

      <h2 id="channels">Drawer channels</h2>
      <ul>
        <li>Choose the channel length to match the drawer’s depth.</li>
        <li>Check the load rating against what the drawer will hold: heavy items need a higher rating.</li>
        <li>
          Telescopic (ball-bearing) channels mount on the drawer sides and need a side gap given in their specification.
          Leave that gap when you size the drawer.
        </li>
        <li>Soft-close channels close the last part of the travel slowly.</li>
      </ul>

      <h2 id="locks">Door locks</h2>
      <ul>
        <li>
          <strong>Mortise locks</strong> fit into a pocket cut in the door edge; <strong>rim locks</strong> mount on the
          inside face; cylindrical and tubular locks fit through bored holes.
        </li>
        <li>Measure the door thickness and check which way the door opens before choosing a lock and handle set.</li>
        <li>Main doors usually need a lock with more levers or a key cylinder; bathroom doors a privacy lock.</li>
      </ul>
      <p>
        Browse <Link to="/c/door-locks-hardware">Door Locks &amp; Hardware</Link>.
      </p>

      <h2 id="glass">Glass door fittings</h2>
      <ul>
        <li>Patch fittings, floor springs and glass handles are made for a range of glass thicknesses. Check that your glass is in that range.</li>
        <li>Frameless glass doors need toughened glass. Holes and cut-outs must be made before the glass is toughened.</li>
        <li>Floor springs are chosen by door weight and width; check both before ordering.</li>
      </ul>
      <p>
        Browse <Link to="/c/glass-door-hardware">Glass Door Hardware</Link>.
      </p>

      <h2 id="tools">Drill bits and power tools</h2>
      <ul>
        <li>Use masonry bits (with hammer mode) for brick and concrete, metal (HSS) bits for steel, and wood bits for timber and boards.</li>
        <li>Match the bit’s shank to your drill’s chuck size, and the bit size to the wall plug or screw.</li>
        <li>For fixings in walls, pick the plug for the wall type and the screw size the plug is made for.</li>
      </ul>
      <p>
        Browse <Link to="/c/power-tools">Power Tools &amp; Accessories</Link> and{' '}
        <Link to="/c/general-hardware">General Hardware &amp; Tools</Link>.
      </p>

      <h2 id="safety">Working safely</h2>
      <ul>
        <li>Wear eye protection when drilling, cutting or grinding.</li>
        <li>Use a dust mask when cutting or sanding boards, especially MDF.</li>
        <li>Wear gloves when handling glass and sheet edges, and unplug power tools before changing bits or blades.</li>
      </ul>
      <p>
        Browse <Link to="/c/safety">Safety Tools &amp; Workwear</Link>. Not sure what you need? <Link to="/contact">Contact us</Link>.
      </p>
    </InfoPage>
  )
}
