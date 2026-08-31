SELECT count(*)
FROM aka_name, complete_cast, info_type, movie_companies, movie_info, name, person_info, title
WHERE movie_companies.note = '(1934) (USA) (theatrical) (as A Columbia Picture)'
  AND person_info.info = 'Stacy Hess is the founder of positivePR, an LA-based public relations firm specializing in working with independent filmmakers, webseries creators and authors, as well as some personal PR representation. She spent the first half of her career in the retail technology sector, and in 2007, decided to jump the corporate ship in order to pursue work that means something to her local and global communities. After a year-long sabbatical spent doing charity work and teaching four to six year-olds to ski in Park City, UT, Stacy started positivePR with two clients and a commitment to doing work that matters with people and projects who also want to impact our world in a positive way.  With nearly 20 years'' experience in public relations, marketing and sales, Stacy brings a unique blend of skills to the table. From managing multi-million dollar budgets for billion dollar corporations, to running sales and marketing departments, all the way through raising investment capital for start ups, she has a history of success under shifting circumstances. This background, combined with her experience in viral grassroots marketing and new media placement, traditional PR, and her collaborative approach to client relationships enables Stacy and her team to consistently deliver results to the positivePR client family.'
  AND aka_name.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
