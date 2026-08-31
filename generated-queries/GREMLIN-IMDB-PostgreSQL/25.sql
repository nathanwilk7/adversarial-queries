SELECT count(*)
FROM aka_name, cast_info, complete_cast, movie_link, name, title
WHERE name.surname_pcode = ''
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
