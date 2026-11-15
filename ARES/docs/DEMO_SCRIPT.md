# Live demo script (v0.3 interface, ~60-90 s)

Start: `python -m ares.api.server`, open http://127.0.0.1:8000, full screen, browser zoom 80% on small projectors.

1. **Mission Overview (5 s):** "Four astronauts, day 200 of a Mars transit, signal delay 8.7 minutes. Everything is green."
2. **Mission Simulation → "7. Emergency during Earth blackout" → Start (5 s):** "The Earth link drops, and an astronaut's
   oxygen starts falling."
3. **3D Health Hologram (25 s):** the lungs, trachea and heart turn red, and the camera flies to the chest. Point at the side
   panel: "Blood oxygen 86% against her own normal of 97.5. ARES found the organs involved, says how sure it is, and what to do
   right now, using a stored procedure that it doesn't invent."
4. **Emergency Command (20 s):** banner "Earth link is DOWN". Click **Acknowledge**, **Request measurements**, **Reading
   confirmed** and **Mark crew notified**, and the workflow steps turn green. "The report waits safely in the queue and sends
   itself when the link returns."
5. **Data & System (5 s):** "And it all runs offline. Every number is labelled real NASA data, simulated, or a model
   estimate."

Backup: if anything fails, play the screen recording. Never debug on stage.
After the demo: Mission Simulation → **Stop** (or **Reset**, ~15 s).
