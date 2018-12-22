var css = document.querySelector("h3");
var color1 = document.querySelector(".color1");
var color2 = document.querySelector(".color2");
var body = document.getElementById("gradient");


body.style.background = 
	"linear-gradient(to right, " 
	+ color1.value 
	+ ", " 
	+ color2.value 
	+ ")";
	css.textContent = body.style.background + ";";


function setGradient() {
	body.style.background = 
	"linear-gradient(to right, " 
	+ color1.value 
	+ ", " 
	+ color2.value 
	+ ")";

	css.textContent = body.style.background + ";";
}

function SetColors() {

	var color1_hex = "#";
	var color2_hex = "#";
	var hex =["0","1","2","3","4","5","6","7","8","9","a","b","c","d","e","f"];
	for ( i=0; i<6;i++)
	{
		
	
	var a =Math.floor(Math.random()*15);
	
	 
	color1_hex = color1_hex.concat(hex[a]);
	 
	var b =Math.floor(Math.random()*15);
	color2_hex = color2_hex.concat(hex[b]);
	//console.log (color2_hex);
   }

	console.log (color1_hex );
	console.log (color2_hex );
 	color1.value =color1_hex;
 	color1.value =color2_hex;
  	setGradient();
}


color1.addEventListener("input", setGradient);

color2.addEventListener("input", setGradient);
